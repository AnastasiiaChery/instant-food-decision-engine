# Развёртывание на прод

> Пошаговый план деплоя NomPilot на прод. Рекомендуемая платформа — **Railway**
> (минимум возни: managed Postgres + Redis в один клик, TLS и домен из коробки,
> деплой из git по [Dockerfile](../Dockerfile)). Альтернативы — Fly.io (дешевле в
> простое, больше настройки) и Render (есть free-tier, но с холодным стартом).
>
> Дата: 2026-06-12.

---

## 0. Что уже готово в коде

- [Dockerfile](../Dockerfile) — на старте сам гонит `alembic upgrade head`, затем uvicorn. Есть `HEALTHCHECK` на `/ready`.
- Миграции БД — [alembic/versions/](../alembic/versions/).
- Rate limiter ([app/core/rate_limit.py](../app/core/rate_limit.py)) — использует Redis, если задан `REDIS_URL` (общие лимиты на все воркеры/инстансы); иначе in-memory.
- LLM — провайдер и модели задаются через env (см. [llm-provider-routing-plan.md](llm-provider-routing-plan.md)). Дефолт: Groq, 70b (heavy) + 8b (fast).
- Fail-fast: в `ENVIRONMENT=production` приложение **не стартует** с дефолтным `JWT_SECRET` или без LLM-ключа ([app/core/config.py](../app/core/config.py)).
- Фронт отдаётся с того же origin → CORS не нужен.

---

## 1. Предварительно (один раз)

### 1.1. LLM — Groq Developer tier
1. [console.groq.com](https://console.groq.com) → **Settings → Billing** → привязать карту (аккаунт перейдёт на Developer tier, лимит 6K→~250K+ TPM).
2. Выставить **spend limit** (например $5/мес) как страховку.
3. Ключ `GROQ_API_KEY` не менять — он же работает на платном tier.

> Запасной вариант (строго $0, но free-tier данные идут в обучение Google): Gemini.
> `AI_PROVIDER=gemini`, `AI_MODEL=gemini-2.5-flash`, `AI_MODEL_FAST=gemini-2.5-flash`,
> `AI_API_KEY=<ключ>` + `pip install langchain-google-genai`. Подробнее — в плане выше.

### 1.2. Сгенерировать JWT_SECRET
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Сохранить — пойдёт в секреты платформы (НЕ в код, НЕ в git).

### 1.3. Google OAuth
1. [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials.
2. В OAuth client добавить в **Authorized redirect URIs**: `https://<твой-домен>/auth/callback`
   (после шага 2.2 ты узнаешь домен — вернись и впиши его).
3. `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — в секреты платформы.

---

## 2. Деплой на Railway

### 2.1. Проект
1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** (или CLI: `railway up`).
2. Railway сам найдёт [Dockerfile](../Dockerfile) и соберёт образ.

### 2.2. Managed-сервисы
1. В проекте → **+ New → Database → PostgreSQL**.
2. **+ New → Database → Redis**.
3. Railway создаст переменные `DATABASE_URL` и `REDIS_URL` и прокинет их в сервис.

> ⚠️ **Важно:** Railway отдаёт `DATABASE_URL` как `postgresql://...`, а приложение
> использует **asyncpg** и ждёт `postgresql+asyncpg://...`. В переменных сервиса
> переопредели `DATABASE_URL`, заменив схему на `postgresql+asyncpg://`
> (можно сослаться на хост/порт/креды из плагина Postgres).

### 2.3. Переменные окружения (Variables в сервисе API)
```
ENVIRONMENT=production
JWT_SECRET=<из шага 1.2>
GROQ_API_KEY=<твой ключ>
GOOGLE_CLIENT_ID=<...>
GOOGLE_CLIENT_SECRET=<...>
GOOGLE_REDIRECT_URI=https://<твой-домен>/auth/callback
DATABASE_URL=postgresql+asyncpg://...   # с поправленной схемой, см. 2.2
REDIS_URL=<из плагина Redis>            # обычно прокидывается автоматически
```
Можно НЕ задавать (есть верные дефолты): `AI_PROVIDER`, `AI_MODEL`, `AI_MODEL_FAST`,
`AI_BASE_URL`, `LOG_LEVEL`, `SEARCH_RADIUS_M`, `MAX_RADIUS_M`.
Опционально: `LANGSMITH_API_KEY` (трейсинг), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (алёрты).

### 2.4. Домен
- Railway выдаёт `https://<сервис>.up.railway.app` (TLS автоматически).
- Впиши этот домен в `GOOGLE_REDIRECT_URI` (шаг 2.3) и в Google Console (шаг 1.3).
- Кастомный домен — позже, через Settings → Networking.

### 2.5. Запуск
- Deploy стартует автоматически. На старте прогонятся миграции, healthcheck дёрнет `/ready`.
- Логи смотреть во вкладке **Deployments → Logs**.

---

## 3. Проверка после деплоя (smoke test)

```bash
curl https://<домен>/health    # {"status":"ok"}
curl https://<домен>/ready     # {"status":"ready","static_available":true}
```
В браузере на `https://<домен>`:
- [ ] открывается главная, грузится UI;
- [ ] **autopilot/search** — выдаёт заведения;
- [ ] **plan-режим** — собирает план (агент с тулами);
- [ ] **вход через Google** — редиректит и логинит (проверяет OAuth + JWT + БД);
- [ ] переключение языка — `/api/v1/i18n/<lang>` отдаёт переведённый словарь.

---

## 4. Масштабирование (когда понадобится)

- Rate limiter уже на Redis → можно увеличивать число воркеров/инстансов без рассинхрона лимитов.
- Несколько воркеров: добавить в CMD `uvicorn ... --workers N` (правка [Dockerfile](../Dockerfile)).
- ⚠️ При **нескольких инстансах одновременно** `alembic upgrade head` на старте может
  гоняться параллельно. Для одного инстанса — не проблема. При мульти-инстансе вынести
  миграции в отдельный release-шаг.

---

## 5. Откат

- **Платформа:** Railway → Deployments → выбрать предыдущий успешный деплой → Redeploy/Rollback.
- **LLM-провайдер:** вернуть `AI_PROVIDER=groq` (или старые переменные) и перезапустить.
- **Миграции:** `alembic downgrade -1` (через `railway run` или shell в контейнере).

---

## 6. Чек-лист «можно запускать»

- [ ] Groq billing включён, spend limit выставлен
- [ ] `JWT_SECRET` сгенерирован и в секретах
- [ ] Postgres + Redis подключены, `DATABASE_URL` со схемой `+asyncpg`
- [ ] Google OAuth redirect добавлен и совпадает с `GOOGLE_REDIRECT_URI`
- [ ] `ENVIRONMENT=production`
- [ ] деплой поднялся, `/ready` отвечает
- [ ] smoke test из §3 пройден
