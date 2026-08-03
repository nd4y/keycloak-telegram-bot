# Telegram-бот для управления группами Keycloak

[🇬🇧 English](README.md) | 🇷🇺 **Русский**

Бот умеет:
- показывать список групп и участников (`/groups`);
- показывать список всех пользователей с постраничной навигацией и карточкой пользователя — его группы, добавление/удаление групп (`/users`);
- создавать группы (`/newgroup Название`);
- добавлять пользователя в группу (поиск по username/email через кнопки, либо из карточки пользователя);
- удалять пользователя из группы, удалять саму группу;
- включать/выключать пользователя (карточка пользователя → кнопка статуса);
- присылать уведомление в Telegram о новых пользователях и/или о каждом входе в Keycloak (проверка раз в `POLL_INTERVAL_SECONDS`, по умолчанию 60 сек) — оба уведомления независимо включаются/выключаются командой `/settings`, дефолт при старте контейнера задаётся переменными `NOTIFY_NEW_USERS` / `NOTIFY_LOGINS`.

Доступ к боту ограничен списком Telegram ID из `ADMIN_CHAT_IDS` — все остальные молча игнорируются.

## 1. Создать service account клиента в Keycloak

Бот ходит в Keycloak через Admin REST API от имени отдельного клиента (client credentials grant), а не под вашим личным логином.

1. Зайдите в admin-консоль: `https://<keycloak-host>/admin/master/console/#/<realm>`.
2. **Clients → Create client**:
   - Client ID: `telegram-bot` (или любой другой, потом указать в `.env`);
   - Client type: `OpenID Connect`, нажмите Next.
3. На шаге **Capability config**:
   - `Client authentication` → **On** (это делает клиента confidential и включает service account);
   - `Authorization` — можно оставить выключенным;
   - `Authentication flow`: включите **Service accounts roles**, остальные (Standard flow, Direct access) можно выключить.
4. Сохраните клиента.
5. Откройте вкладку **Credentials** у созданного клиента — скопируйте `Client secret`, он пойдёт в `KEYCLOAK_CLIENT_SECRET`.
6. Откройте вкладку **Service account roles** → **Assign role**:
   - переключитесь на `Filter by clients`;
   - найдите клиента `realm-management` и назначьте роли:
     - `manage-users` — создание/удаление пользователей из групп, включение/отключение пользователя;
     - `query-users` — поиск и листинг пользователей;
     - `query-groups` и `manage-realm` (или хотя бы `view-realm`) — работа с группами;
     - `view-events` — чтение событий входа (нужно только для `NOTIFY_LOGINS`).
   - Если не уверены, какую роль выбрать — можно временно выдать `realm-admin` (полные права от `realm-management`), а потом сузить.

Итог: у вас есть `Client ID` = `telegram-bot`, `Client secret` = длинная строка, realm = `<realm>`, url = `https://<keycloak-host>`.

### Опционально: включить логирование входов (для `NOTIFY_LOGINS`)

Keycloak по умолчанию не сохраняет события входа — Admin REST API просто вернёт пустой список, даже если роль `view-events` выдана. Чтобы уведомления о входах вообще могли на что-то сработать:

1. В admin-консоли: **Realm settings → Events → User events settings**.
2. Включите **Save events**.
3. В **Saved event types** добавьте (или убедитесь, что есть) `LOGIN`.
4. Обратите внимание на **Expiration** — Keycloak будет копить эти события в своей БД, старые нужно чистить (задайте разумный TTL, например 1-2 недели), чтобы не раздувать базу.

Это меняет поведение realm целиком (события пишутся для всех клиентов, не только для бота), поэтому включайте осознанно — это не то же самое, что просто настройка самого бота.

## 2. Создать Telegram-бота

1. В Telegram напишите [@BotFather](https://t.me/BotFather) → `/newbot`, следуйте инструкциям.
2. Получите токен вида `123456789:AA...` — это `TELEGRAM_BOT_TOKEN`.
3. Узнайте свой Telegram ID: напишите [@userinfobot](https://t.me/userinfobot) — он пришлёт ваш числовой ID. Это значение пойдёт в `ADMIN_CHAT_IDS` (через запятую можно перечислить несколько ID, если админов несколько).

## 3. Настроить .env

```bash
cp .env.example .env
```

Заполните все поля: `TELEGRAM_BOT_TOKEN`, `ADMIN_CHAT_IDS`, `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`.

`NOTIFY_NEW_USERS` / `NOTIFY_LOGINS` — дефолтное состояние уведомлений при старте контейнера; переключаются на лету командой `/settings` в самом боте, без рестарта. `PERSIST_SETTINGS` решает, переживает ли переключение через `/settings` рестарт контейнера:
- `false` (по умолчанию) — после рестарта состояние снова берётся из `NOTIFY_NEW_USERS`/`NOTIFY_LOGINS`. Так и должно быть, если `data/` не смонтирован как постоянный том (например, под k8s без PVC) — иначе настройка "сохранится", но будет молча теряться при каждом пересоздании пода.
- `true` — переключение через `/settings` пишется в `data/settings.json` и переживает рестарт. Включайте, только если `data/` — реальный persistent volume/bind mount.

## 4. Запуск через Docker

```bash
docker compose up -d --build
docker compose logs -f
```

Данные о том, каких пользователей бот уже видел (чтобы не спамить уведомлениями при первом запуске), хранятся в `./data/seen_users.json`; момент последнего обработанного события входа — в `./data/last_login_event.json`. При первом старте бот "снимает снимок" текущего состояния и присылает уведомления только о том, что появилось после этого момента. Если `PERSIST_SETTINGS=true`, туда же (`./data/settings.json`) пишутся переключения `/settings`.

## 4b. Деплой через Portainer (без git-репозитория и без внешнего registry)

Если исходники лежат только локально (не в git) и хочется развернуть на Docker-хосте, которым управляет Portainer:

1. Собрать образ прямо на Docker-engine, которым управляет Portainer, через Docker Build API (Portainer его проксирует):
   ```bash
   tar -cf build-context.tar Dockerfile requirements.txt bot
   curl -sk -X POST \
     -H "X-API-Key: <PORTAINER_API_TOKEN>" \
     -H "Content-Type: application/x-tar" \
     --data-binary @build-context.tar \
     "https://<portainer-host>:9443/api/endpoints/<ENDPOINT_ID>/docker/build?t=keycloak-telegram-bot:latest"
   ```
   `ENDPOINT_ID` — id нужного Docker-окружения, смотрится через `GET /api/endpoints`.
2. Развернуть стек `docker-compose.portainer.yml` (использует уже собранный `image:` вместо `build:`, а секреты передаются переменными окружения, а не файлом `.env`, — Portainer его на хост не копирует):
   ```bash
   curl -sk -X POST \
     -H "X-API-Key: <PORTAINER_API_TOKEN>" \
     -H "Content-Type: application/json" \
     -d @stack-payload.json \
     "https://<portainer-host>:9443/api/stacks?type=2&method=string&endpointId=<ENDPOINT_ID>"
   ```
   где `stack-payload.json` содержит `{"Name": "...", "StackFileContent": "<содержимое docker-compose.portainer.yml>", "Env": [{"name": "TELEGRAM_BOT_TOKEN", "value": "..."}, ...]}`.

При изменении кода: пересобрать образ шагом 1 (перезапишет тег `latest`), затем в Portainer сделать Update/Redeploy стека, чтобы он подхватил новый образ.

## 5. Запуск без Docker (локально)

```bash
python -m venv .venv
source .venv/bin/activate  # или .venv\Scripts\activate на Windows
pip install -r requirements.txt
cp .env.example .env  # и заполнить
python -m bot.main
```

## Структура проекта

```
bot/
  config.py           — чтение настроек из .env
  keycloak_client.py   — асинхронная обёртка над Keycloak Admin REST API
  storage.py           — файл-хранилища "уже виденных" ID пользователей и последнего события входа
  settings.py           — переключатели уведомлений (env-дефолт + опциональная персистентность)
  callback_cache.py    — короткие токены для inline-кнопок Telegram
  middleware.py        — ограничение доступа по ADMIN_CHAT_IDS
  handlers.py          — команды и inline-меню (/groups, /users, /settings, /newgroup, ...)
  notifier.py          — фоновый опрос Keycloak и уведомления о новых юзерах и входах
  main.py              — точка входа
```

## Известные ограничения (MVP)

- Поддерживаются только группы верхнего уровня (без вложенных подгрупп).
- Уведомления о новых пользователях и о входах — по опросу (polling), а не мгновенно по событию; задержка до `POLL_INTERVAL_SECONDS`. Для мгновенных уведомлений нужен кастомный Keycloak Event Listener SPI на самом сервере — это отдельная задача, если понадобится.
- Опрос входов запрашивает последние 200 событий за цикл; если между опросами произойдёт больше 200 входов, часть уведомлений может быть пропущена (для личного/небольшого realm'а маловероятно).
