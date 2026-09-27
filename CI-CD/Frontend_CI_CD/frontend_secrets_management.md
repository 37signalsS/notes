**Актуально для:** Vault 1.15+, GitLab CI 16+

# Secrets Management для фронтенд CI/CD

## Определения

- **Dynamic Secret** — секрет, создаваемый Vault на запрос и имеющий TTL; после истечения автоматически revoked.
- **AppRole** — механизм аутентификации в Vault, предназначенный для машинных рабочих нагрузок, включая CI/CD раннеры.
- **JWT/OIDC Auth** — аутентификация по JWT-токену платформы CI (GitLab) с привязкой политик к claims runner/проеккта.
- **Secret Rotation** — автоматическая замена паролей/ключей без изменения конфигурации потребителей.
- **Vault Agent** — вспомогательный процесс, кэширующий токен и отдающий секреты через sidecar/injector.
- **Response Wrapping** — выдача секрета не напрямую, а через одноразовый wrapping-token с коротким TTL.
- **Preview Environment** — временная среда для ревью Merge Request, требующая изолированных секретов от production.
- **npm Registry Token** — учетные данные для доступа к приватному npm-реестру, необходимые только на этапе сборки.
- **CDN/FFaaS Token** — токен доступа к CDN или Feature-as-a-Service провайдеру, часто имеющий широкие права на всю зону.

---

## Предварительные требования

- **Vault:** инициализированный и распечатанный кластер (версия 1.15+), KV v2 включён на пути `secret/`, включён audit device.
- **CI/CD:** GitLab CI 16+ с self-hosted раннерами, имеющими сетевая доступность до Vault API (порт 8200).
- **Сеть:** egress от раннеров к Vault разрешён; для runtime (SSR) — egress от пода к Vault через NetworkPolicy.
- **Раннер:** dedicated frontend-раннер или общий с изоляцией job'ов; рекомендуется ephemeral-режим.
- **Приложение:** SSR-процесс (Node.js) поддерживает чтение секретов из файла или окружения и graceful reload по `SIGHUP`.
- **Документация:** общие принципы управления секретами описаны в **[Управление секретами в CI/CD](../../CI-CD/DevSecOps/secrets_management.md)**; этот файл фокусируется на фронтенд-специфике.

---

## Основные концепции

### Почему обычные CI variables недостаточны

GitLab CI Variables подходят для статических токенов, но не дают:
- rotation без повторного деплоя пайплайна;
- краткоживущих credentials для баз/реестров;
- аудита каждого чтения секрета;
- разделения секретов по окружениям/проекктам без дублирования.

Для фронтенда особенно важны rotation и least privilege, потому что CDN/edge токены и FFaaS ключи часто имеют широкие права на всю зону.

### Архитектура интеграции Vault с GitLab CI

Классический паттерн: GitLab Runner аутентифицируется в Vault через AppRole или JWT, получает временный токен и читает только разрешённые пути. Секрет никогда не попадает в лог CI, а в приложение/SSR-процесс он передаётся через env или временный файл.

Варианты доставки:
- **CI-time:** секрет читается в пайплайне и передаётся как masked variable в окружение.
- **Runtime-time:** Vault Agent sidecar или CSI Driver delivers секреты напрямую в SSR-под/процесс.
- **Hybrid:** CI получает краткоживущий токен доступа к внешнему API, а долгоживущие секреты остаются в Vault и читаются при старте процесса.

### AppRole для GitLab CI

AppRole состоит из `role-id` (публичный идентификатор) и `secret-id` (секретный, одноразовый или с TTL). Runner хранит `role-id` в CI/CD Variables, а `secret-id` запрашивается через JWT-аутентификацию GitLab. Это исключает хранение статических токенов в репозитории.

Политика Vault должна ограничивать доступ по:
- проекту/группе GitLab (`ci-project-path`);
- типу окружения (`review/*` vs `production`);
- путям секретов (`kv/data/frontend/*`).

### Build-time секреты фронтенда

Секреты, необходимые на этапе сборки:
- **npm/pnpm registry token:** доступ к приватным пакетам; должен жить только во время `npm ci`.
- **GPG/Cosign ключ:** подпись артефактов; передаётся через Vault и никогда не попадает в слой образа.
- **CDN origin token:** загрузка артефактов в origin-хранилище remote.

Принцип: build-time секреты запрашиваются через Vault в момент выполнения шага и не передаются между этапами пайплайна. Общая таблица угроз — в **[Управление секретами в CI/CD](../../CI-CD/DevSecOps/secrets_management.md)**.

### Runtime-конфигурация для SSR

Секреты SSR-процесса (DB, API, CDN) не должны попадать в билд. Паттерн:
1. Vault Agent sidecar запускается вместе с Node процессом.
2. При старте Agent запрашивает секреты и записывает их в shared memory или tmpfs.
3. Node читает секрет из файла/окружения и удаляет путь из окружения после загрузки.

Для systemd-юнита можно использовать `EnvironmentFile`, генерируемый Vault Agent перед стартом.

### Разделение секретов по окружениям

- **Preview/MR:** изолированные секреты от production; Vault политика ограничивает путь `kv/data/frontend/review/*`.
- **Production:** секреты с максимальным TTL, отдельная политика, аудит каждого чтения.
- **Static/SSG:** если секреты не нужны в рантайме — исключить их из билда полностью; использовать переменные окружения только для нечувствительных флагов.

---

## Практические сценарии

### Сценарий 1: AppRole + JWT auth для GitLab CI

```bash
# 1. Создаём политику
vault policy write ci-frontend - <<EOF
path "kv/data/frontend/{{identity.entity_id}}" {
  capabilities = ["read"]
}
path "kv/metadata/frontend/" {
  capabilities = ["list", "read"]
}
EOF

# 2. Создаём JWT-роль, привязываем политику
vault write auth/jwt/role/ci-frontend \
  bound_issuer="https://gitlab.com" \
  bound_subject="project_path:org/frontend:ref_type:branch:ref:main" \
  policies="ci-frontend" \
  ttl=1h
```

```yaml
# .gitlab-ci.yml
variables:
  VAULT_ADDR: "https://vault.internal.corp"

stages:
  - deploy

deploy_production:
  stage: deploy
  image: alpine:latest
  script:
    - apk add --no-cache curl jq
    - |
      JWT=$(cat /scripts/vault/jwt)
      VAULT_TOKEN=$(curl -s -X POST "$VAULT_ADDR/v1/auth/jwt/login" \
        -H "Authorization: Bearer $JWT" \
        -d '{"role":"ci-frontend"}' | jq -r '.auth.client_token')
      curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
        "$VAULT_ADDR/v1/kv/data/frontend/production/cdn-token" | jq '.data.data'
  only:
    - main
```

**Валидация:**
- `vault read auth/jwt/role/ci-frontend` → роль существует, политика `ci-frontend` привязана, TTL = 1h.
- Пайплайн завершается успешно; в логах CI нет значения секрета (masked).

**Troubleshooting:**
- *403 / permission denied:* проверьте `bound_subject` — он должен точно совпадать с JWT, выпущенным GitLab Runner.
- *Политика не даёт доступ:* убедитесь, что путь в политике (`kv/data/frontend/...`) совпадает с запрашиваемым.
- *Токен истёк слишком быстро:* увеличьте `ttl` или настройте Vault Agent с auto-renew.

### Сценарий 2: Response Wrapping для секретов в пайплайне

```bash
# 1. Заворачиваем секрет (TTL 10 минут)
WRAPPING_TOKEN=$(vault write -wrap-ttl=600 \
  -field=wrapping_token \
  kv/data/frontend/production/api-key)

# 2. Передаём wrapping-token в CI как переменная
echo "WRAPPING_TOKEN=$WRAPPING_TOKEN" >> secure_variables

# 3. В пайплайне раскрываем
API_KEY=$(vault unwrap -field=value kv/data/frontend/production/api-key "$WRAPPING_TOKEN")
```

**Валидация:**
- `vault unwrap -meta $WRAPPING_TOKEN` возвращает секрет.
- Повторный unwrap того же токена завершается ошибкой `already unwrapped`.

**Troubleshooting:**
- *Wrapping token истёк:* `wrap-ttl` слишком мал для времени доставки в CI — увеличьте до 600–3600s.
- *already unwrapped:* wrapping token уже использован — запросите новый.

### Сценарий 3: Vault Agent sidecar для SSR

```yaml
# systemd unit или docker-compose
services:
  frontend-ssr:
    image: node:22-bookworm
    command: ["node", "server.js"]
    environment:
      VAULT_ADDR: "http://vault-agent:8200"
    depends_on:
      vault-agent:
        condition: service_healthy

  vault-agent:
    image: vault:1.15
    command: ["vault", "agent", "-config=/vault/config/agent.hcl"]
    volumes:
      - ./vault/config:/vault/config
      - /vault/secrets:/secrets:shared
    healthcheck:
      test: ["CMD", "vault", "status"]
```

```hcl
# agent.hcl
auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path = "/vault/secrets/role-id"
      secret_id_file_path = "/vault/secrets/secret-id"
    }
  }
}

cache {
  use_auto_auth_token = true
}

template {
  source      = "/vault/config/templates/cdn-token.tmpl"
  destination = "/secrets/cdn-token"
}
```

**Валидация:**
- `vault status` в sidecar возвращает `Sealed: false`.
- Файл `/secrets/cdn-token` содержит актуальный токен; после `vault write -force` файл обновляется.

**Troubleshooting:**
- *Агент не стартует:* проверьте права на `agent.hcl` и пути к `role-id`/`secret-id`.
- *Секрет не обновляется:* проверьте `static_secret_render_interval` в `template_config` (по умолчанию 10m) или отправьте `SIGHUP`.
- *permission denied:* политика Vault не покрывает путь секрета.

### Сценарий 4: Rotate CDN токен через Vault

```bash
# 1. Генерация нового токена в Vault
vault write -force kv/data/frontend/production/cdn-token

# 2. SSR-процесс перечитывает секрет (SIGHUP или polling)
kill -HUP $(pgrep -f "node server.js")

# 3. Валидация: новый токен работает, старый revoked
curl -I https://cdn.example.com/assets/app.js \
  -H "Authorization: Bearer $NEW_TOKEN"
```

**Валидация:**
- Старый токен возвращает `403` после ротации.
- Новый токен возвращает `200`; SSR-процесс перезапустился без даунтайма.

**Troubleshooting:**
- *Ротация ломает прод:* SSR кэширует старый токен — добавьте graceful reload или используйте Vault Agent.
- *Старый токен всё ещё работает:* TTL Vault длиннее времени кэширования в CDN — снизьте TTL или настроить cache busting.

### Сценарий 5: npm registry token через Vault (build-time)

```yaml
# .gitlab-ci.yml
install_deps:
  stage: build
  image: node:22-bookworm
  variables:
    VAULT_ADDR: "https://vault.internal.corp"
  script:
    - apk add --no-cache curl jq
    - |
      JWT=$(cat /scripts/vault/jwt)
      VAULT_TOKEN=$(curl -s -X POST "$VAULT_ADDR/v1/auth/jwt/login" \
        -H "Authorization: Bearer $JWT" \
        -d '{"role":"ci-frontend"}' | jq -r '.auth.client_token')
      NPM_TOKEN=$(curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
        "$VAULT_ADDR/v1/kv/data/frontend/production/npm-token" | jq -r '.data.data.token')
      npm ci --registry=https://registry.npmjs.org/
      # Токен больше не нужен — не передаём в следующие этапы
  only:
    - merge_requests
    - main
```

**Валидация:**
- `npm ci` завершается успешно; в логах CI нет значения `NPM_TOKEN`.
- Следующие этапы не имеют доступа к `NPM_TOKEN`.

**Troubleshooting:**
- *401 от npm registry:* токен отозван или истёк TTL — проверьте Vault audit log.
- *Секрет в логе CI:* `npm` печатал токен в debug-режиме — отключите `--loglevel verbose` или используйте `npm_config_` префикс.

---

## Операционные команды

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `vault kv get secret/frontend/production/cdn-token` | Чтение секрета | # → вывод ключ-значение |
| `vault kv put secret/frontend/production/cdn-token token=xxx` | Запись секрета | # → подтверждение успешной записи |
| `vault write -force secret/data/frontend/production/cdn-token` | Генерация нового значения | # → новый `version` в KV v2 |
| `vault write -wrap-ttl=600 -field=wrapping_token secret/data/frontend/production/api-key` | Обёртывание секрета | # → `wrapping_token` с TTL 600s |
| `vault unwrap -field=value -token-only $WRAPPING_TOKEN` | Распаковка wrapping токена | # → значение секрета |
| `vault read auth/jwt/role/ci-frontend` | Проверка JWT-роли | # → конфигурация роли, политики, TTL |
| `vault read auth/approle/role/ci-frontend/role-id` | Получение Role-ID (публичный) | # → role-id для CI Variables |
| `vault audit enable file file_path=/var/log/vault/audit.log` | Включение аудит-логирования | # → подтверждение включения |
| `vault token capabilities secret/frontend/production/cdn-token` | Проверка прав токена | # → `read` или `deny` |

---

## Валидация

- **JWT auth работает:** `vault read auth/jwt/role/ci-frontend` → роль существует, политика привязана, TTL совпадает с длительностью job.
- **Пайплайн читает секрет:** в логе CI нет значения секрета (masked), но job возвращает `200` и данные.
- **Rotation без деплоя:** после `vault write -force` новый токен работает, старый — `403`.
- **Least privilege:** попытка читать путь за пределами `frontend/*` возвращает `403`.
- **Vault Audit Log:** операция чтения присутствует в логе с `identity.entity_id` проекта.
- **Vault Agent sidecar:** файл секрета обновлён, процесс получил `SIGHUP`, приложение перечитало конфиг без рестарта.
- **npm registry token:** `npm ci` проходит; токен не остаётся в переменных окружения следующих этапов.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Секрет в логе CI | `curl` с токеном не замаскирован | Использовать `VAULT_TOKEN` как masked variable |
| Ротация ломает прод | SSR не перечитывает секрет | SIGHUP + graceful reload, или Vault Agent |
| npm registry 401 | Токен отозван или истёк TTL | Проверить Vault audit log; выдать новый токен |
| Долгий старт SSR | Vault Agent ждёт таймаут при недоступности Vault | Настроить `retry` в `vault { ... }` блоке; `num_retries = 5` |
| Wrap token истёк | `wrap-ttl` меньше времени доставки в CI | Увеличить `wrap-ttl` до 600–3600s |
| SecretID истёк | Wrap-токен живёт `wrap-ttl` секунд | Перевыпустить через `vault write -wrap-ttl=60s auth/approle/role/.../secret-id` |
| Пайплайн не маскирует секрет | Переменная не помечена как masked | Добавить переменную в `protected/masked` CI Variables |
| SSR видит старый секрет | Кэш Agent не обновлён | `vault agent` с `static_secret_render_interval` или `SIGHUP` |
| Vault permission denied | Политика не покрывает путь или capability | Выполнить `vault token capabilities <path>` для диагностики |

---

## Инцидент: утечка секрета фронтенда

1. **Немедленный отзыв:** отозвать скомпрометированный ключ/CDN-токен в панели управления провайдера.
2. **Ротация:** сгенерировать новые учетные данные в Vault.
3. **Очистка истории:** использовать BFG Repo-Cleaner или `git filter-repo` для удаления следов секрета.
4. **Аудит:** проверить Vault Audit Logs и логи CI на предмет подозрительной активности в период утечки.
5. **Уроки:** blameless postmortem, обновление политик доступа и правил сканеров.

Полный runbook — в **[Управление секретами в CI/CD](../../CI-CD/DevSecOps/secrets_management.md)**.

---

## Лучшие практики

1. Никогда не храните статические секреты в CI variables, если Vault может выдать dynamic secret с TTL.
2. Используйте AppRole или JWT auth с привязкой к GitLab claims, а не статический токен.
3. Политика Vault для фронтенда: только чтение нужных путей, отдельная роль на `review/*` и `production`.
4. В пайплайне используйте Response Wrapping, чтобы не передавать секрет напрямую.
5. Для SSR предпочитайте Vault Agent sidecar или CSI Driver, а не чтение секретов в CI.
6. Настройте rotation для CDN/FFaaS токенов с TTL короче, чем максимальное время деплоя.
7. Включите Audit Log в Vault и коррелируйте чтения секретов с deploy_version в RUM.
8. Храните `role-id` в CI/CD Variables, а `secret-id` запрашивайте через JWT каждый запуск.
9. Build-time секреты (npm, registry) должны жить только во время конкретного шага и не попадать в образ или лог.
10. Для preview-окружений используйте отдельные пути Vault (`review/*`) с политиками, исключающими доступ к production.

---

## Дополнительная информация

### См. также

- **[Обзор HashiCorp Vault](../../Vault/overview.md)** — архитектура SLM и движки секретов.
- **[Управление секретами в CI/CD](../../CI-CD/DevSecOps/secrets_management.md)** — общие принципы, threat model, ротация, incident response.
- **[Vault Agent](../../Vault/guides/vault_agent/basics.md)** — sidecar, injector, кэширование токенов.
