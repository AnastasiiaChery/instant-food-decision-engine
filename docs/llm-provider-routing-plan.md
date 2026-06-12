# План: переключаемый LLM-провайдер + роутинг моделей по задаче

> Статус: **реализовано** (2026-06-12). Шаги 1–8 выполнены, все тесты зелёные (41 passed).
> Цель — снять зависимость от бесплатного tier Groq на проде, сделать выбор провайдера
> и модели вопросом `.env`, а не нового релиза.
>
> Осталось только эксплуатационное (см. «Перед запуском» внизу): включить billing на Groq
> (Developer tier) либо переключить `AI_PROVIDER=gemini`, и перепроверить актуальные лимиты/цены.

## Контекст и мотивация

Проект разворачивается на прод. Сейчас все LLM-вызовы идут через **Groq free tier**
(`llama-3.3-70b-versatile`). Узкое место бесплатного tier — **6 000 TPM** (а не дневной
лимит запросов): на 2–3 одновременных пользователях запросы начнут получать `429`,
потому что в ranker/planner в промпт уходит JSON со списком заведений + интентом
(тяжёлые запросы).

На каждое действие пользователя — 2–3 LLM-вызова.

### Решение (выбрано)

Сделать провайдер и модель на каждый шаг конфигурируемыми через `.env`. Дефолт:
- провайдер **Groq Developer tier** (pay-as-you-go: включить billing, код не меняется,
  лимиты ×~40 по TPM, цена копеечная при дотрафике монетизации);
- **роутинг моделей по задаче**: лёгкие шаги на `llama-3.1-8b-instant` (~в 10x дешевле
  и быстрее), тяжёлые — на `llama-3.3-70b-versatile`;
- **Gemini 2.5 Flash** — запасной аэродром, переключается одной переменной окружения.

### Сравнение опций (на момент 2026-06, проверять перед запуском)

| Вариант | Лимиты | Цена | Код менять? | Приватность |
|---|---|---|---|---|
| Groq Free (текущий) | 30 RPM / **6K TPM** / 14.4K req/день | $0 | — | ок |
| **Groq Developer** (pay-as-you-go) | ~1000 RPM / 250–300K TPM | 70b: $0.59/$0.79 за 1М; 8b: $0.05/$0.08 | нет, только привязать карту | ок (не тренируют) |
| Gemini 2.5 Flash Free | 10 RPM / **1M TPM** / 1500 req/день | $0 | да (сменить клиент) | ⚠️ free-tier данные идут в обучение |

Источники (проверить актуальность перед запуском):
- Groq rate limits — https://console.groq.com/docs/rate-limits
- Groq pricing — https://groq.com/pricing
- Gemini rate limits — https://ai.google.dev/gemini-api/docs/rate-limits
- Gemini pricing — https://ai.google.dev/gemini-api/docs/pricing

---

## Текущая архитектура (что трогаем)

Один клиент `ChatGroq` создаётся в `app/main.py:49`, кладётся в `app.state.ai_client`
и одним объектом протекает во все 4 LLM-шага:

- `parse_intent` — `app/services/search_service.py:346` — **лёгкий**
- `rank_places` — `app/services/search_service.py:450` — **тяжёлый**
- `plan_places` — `app/services/search_service.py:391` — **тяжёлый** (агент с тулами)
- `get_translations` — `app/api/v1/routes/i18n.py:14` — **лёгкий**, кешируется на диск/Redis

Типы везде жёстко прибиты к `ChatGroq`. В `app/services/planner.py:193` есть
groq-специфичный `except groq.BadRequestError` (`tool_use_failed`).

---

## Шаги имплементации

### 1. Конфиг — `app/core/config.py`
Добавить (с обратной совместимостью со старыми `groq_api_key` / `ai_model`):

```python
# Провайдер: "groq" (дефолт) | "openai" | "gemini"
ai_provider: str = "groq"
ai_api_key: str = ""          # общий ключ; если пуст — фолбэк на groq_api_key
ai_base_url: str = "https://api.groq.com/openai/v1"

# Две модельные «полки»
ai_model: str = "llama-3.3-70b-versatile"   # heavy: ranker, planner
ai_model_fast: str = "llama-3.1-8b-instant" # light: intent, translator
```
- В `validate_runtime()` заменить проверку `groq_api_key` на «ключ выбранного провайдера не пуст».
- Добавить `effective_api_key` property (`ai_api_key or groq_api_key`).

### 2. Фабрика клиентов — `app/core/deps.py`
Заменить `get_ai_client()` на:
```python
def build_llm(model: str) -> BaseChatModel: ...      # роутит по ai_provider
def build_ai_clients() -> dict[str, BaseChatModel]   # {"fast": ..., "heavy": ...}
```
- `groq` → оставить `ChatGroq` (меньше риск регрессий со structured output).
- `openai`/openai-совместимые → `ChatOpenAI(base_url=...)`.
- `gemini` → `ChatGoogleGenerativeAI` (пакет `langchain-google-genai`).
- Кэшировать инстансы (создавать один раз на старте, не на запрос).

### 3. Старт приложения — `app/main.py:49`
`app.state.ai_clients = build_ai_clients()` (dict с `fast`/`heavy`).
Оставить `app.state.ai_client = clients["heavy"]` для обратной совместимости.

### 4. Прокинуть нужную полку в каждый шаг
- `app/api/v1/routes/search.py:35` и `app/api/v1/routes/i18n.py:14`: доставать из `app.state.ai_clients`.
- `app/services/search_service.py`: `stream_search` принимает оба клиента (или весь dict);
  `parse_intent` ← `fast`, `rank_places` / `plan_places` ← `heavy`.
- `app/api/v1/routes/i18n.py`: `get_translations` ← `fast`.

### 5. Снять привязку к типу `ChatGroq`
Заменить аннотации `ChatGroq` → `BaseChatModel`
(`langchain_core.language_models.BaseChatModel`) в:
`app/services/intent_parser.py`, `app/services/ranker.py`,
`app/services/planner.py`, `app/services/translator.py`.
Чисто типы, рантайм не меняется.

### 6. Убрать groq-специфику из планировщика — `app/services/planner.py:193`
`except groq.BadRequestError` сработает только на groq. Обернуть так, чтобы для других
провайдеров retry на `tool_use_failed` не падал: проверять мягко через
`getattr(exc, "code", None)`, groq-импорт сделать опциональным.

### 7. Документация + окружение
- `.env.example`: описать `AI_PROVIDER`, `AI_MODEL`, `AI_MODEL_FAST`, `AI_API_KEY`,
  примеры для Groq и Gemini.
- `requirements.txt`: `langchain-openai`, `langchain-google-genai`
  (последний — опционально, под gemini).

### 8. Тесты — `tests/test_prod_safeguards.py`
- Поправить тест на `validate_runtime` под новую проверку ключа.
- Добавить тест: `build_ai_clients()` для каждого провайдера возвращает корректные
  модели на fast/heavy; фолбэк `ai_api_key → groq_api_key` работает.

---

## Edge cases
- **Структурированный вывод на Gemini.** `with_structured_output` и `bind_tools` в
  `langchain-google-genai` работают, но `.bind(response_format={"type":"json_object"})`
  в `app/services/translator.py:86` — это OpenAI-формат. Для gemini заменить на
  провайдеро-нейтральный путь (`with_structured_output` или убрать bind для не-openai).
- **Обратная совместимость.** Если в `.env` заданы только старые `GROQ_API_KEY` /
  `AI_MODEL` — всё работает как раньше (fast-полка дефолтится на 8b).
- Все существующие фолбэки (`_fallback_ranking`, `_fallback_recommendations`, дефолтный
  интент) остаются — деградация при сбое LLM не меняется.

---

## Порядок работ
1. Шаги 1–6: ядро на Groq + роутинг 8b/70b (почти чистый рефактор, без смены поведения).
2. Шаги 7–8: gemini-ветка + тесты (изолирована, не активна пока `AI_PROVIDER=groq`).

## Оценка
~30–40 мин. Риск низкий.

## Перед запуском (TODO)
- [ ] Перепроверить актуальные лимиты и цены Groq/Gemini по ссылкам выше.
- [ ] Решить дефолтного провайдера на проде (Groq pay-as-you-go vs Gemini free).
- [ ] Включить billing на Groq, если идём через Developer tier.
