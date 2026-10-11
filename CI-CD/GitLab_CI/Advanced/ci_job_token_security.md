# CI_JOB_TOKEN: attack surface и аудит

**Актуально для:** GitLab 18.0–19.4

## Требования и предварительные условия

| Параметр | Значение |
| :--- | :--- |
| **Версия GitLab** | 18.0+ (Inbound Allowlist), 18.3+ (Fine-grained Permissions), 18.4+ (git push), 19.x (текущая линия) |
| **Роль** | DevOps, SRE, Sysadmin |
| **Необходимые знания** | GitLab CI/CD architecture, REST API, Sidekiq, audit logging, Fine-grained Permissions, Project/Group Access Tokens |
| **SSoT по теме** | [Переменные и секреты GitLab CI](../Concepts/gitlab_ci_variables_secrets.md), [CI/CD Security Hardening](../Advanced/cicd_security_hardening.md), [Внутренности пайплайнов](../Advanced/pipeline_execution_model.md) |

**Для кого:** DevOps-инженеры, проектирующие безопасную архитектуру CI/CD; SRE, настраивающие мониторинг и алерты на утечки; Sysadmin, управляющие self-managed инстансами и политиками аудита.

## Определения

**CI_JOB_TOKEN** — краткоживущий токен, автоматически создаваемый для каждого job. Используется для аутентификации внутри job: клонирование репозитория, загрузка артефактов, доступ к Container Registry, вызов API других проектов. По умолчанию живёт в рамках одного job и имеет scope проекта, в котором выполняется пайплайн.

**Inbound Allowlist (Authorized groups and projects)** — белый список проектов/групп, чьи `CI_JOB_TOKEN` могут обращаться к текущему проекту через API. Начиная с GitLab 18.0, межпроектные вызовы через `CI_JOB_TOKEN` требуют явной записи в allowlist.

**Workload Identity Federation** — модель Zero Trust, при которой раннер получает краткоживущий JWT (ID Token), а аудитория (`aud`) проверяется внешним identity-провайдером. Исключает необходимость хранения статических секретов.

**Protected runners** — раннеры, доступные только для защищенных веток и тегов. Защищают секреты от доступа через fork-проекты и неподписанные MR.

**Fine-grained Permissions (18.3+)** — тонкая настройка прав для `CI_JOB_TOKEN`, позволяющая ограничить токен конкретными разрешениями (`read_registry`, `write_pages`, `read_api` и т.д.) вместо полного scope проекта.

**Token scope** — набор разрешений и ресурсов, к которым токен имеет доступ. У `CI_JOB_TOKEN` scope ограничен проектом по умолчанию; может быть расширен через allowlist или Fine-grained Permissions.

**Masked variable** — переменная, значение которой скрывается в логах (`[MASKED]`). С версии 18.3 применяется автоматически ко всем новым переменным. Требование: минимум 8 символов, отсутствие пробелов.

**Audit logging** — запись событий безопасности в журнал аудита GitLab. Позволяет отслеживать создание, использование и отзыв токенов, межпроектные вызовы, изменения настроек доступа.

**Cross-project token access** — возможность использования `CI_JOB_TOKEN` одного проекта для доступа к API другого проекта. Требует явного разрешения через Inbound Allowlist (18.0+).

## Attack surface CI_JOB_TOKEN

| Вектор атаки | Описание | Риск | Смягчение |
| :--- | :--- | :--- | :--- |
| **Утечка в логи** | Токен выводится в лог job (например, при отладке `curl -v`) | Компрометация проекта | `masked: true`, `protected: true`, аудит логов |
| **Передача по SSH** | Токен передаётся в downstream-пайплайн или на удалённый хост через SSH | Компрометация downstream-проектов | Project Access Token с ограниченным scope |
| **Артефакты** | Токен попадает в артефакт и становится доступен всем, кто имеет доступ к артефакту | Компрометация проекта | `artifacts:exclude`, `.gitlabignore` |
| **Fork-проекты** | В fork-проекте злоумышленник может получить доступ к CI_JOB_TOKEN upstream-проекта | Компрометация upstream | Protected runners, inbound allowlist |
| **Malicious job** | Вредоносный код в job использует CI_JOB_TOKEN для эксфильтрации данных | Данные, секреты, артефакты | Minimal permissions, OIDC вместо CI_JOB_TOKEN |
| **Replay attack** | Токен перехвачен и использован повторно в рамках TTL | Компрометация | Короткий TTL, audit logging |
| **Cache poisoning** | Токен сохраняется в кэше job и становится доступен в последующих запусках | Компрометация | `cache:key` с уникальным значением, отключение кэша для чувствительных операций |
| **Dependency confusion** | Вредоносный артефакт в реестре перехватывает вызовы, аутентифицированные через CI_JOB_TOKEN | Цепочечная атака | Верификация зависимостей, allowlist реестров, signed images |

## Основные концепции

### Жизненный цикл CI_JOB_TOKEN

`CI_JOB_TOKEN` создаётся автоматически при старте job и существует только в течение его выполнения. После завершения job токен отзывается. Scope токена по умолчанию ограничен проектом, в котором выполняется пайплайн.

### Механизм Inbound Allowlist

Начиная с GitLab 18.0, межпроектные вызовы через `CI_JOB_TOKEN` требуют явного разрешения:

1. В целевом проекте включается `Settings → CI/CD → Token Access → Authorized groups and projects`.
2. Добавляется источник (проект или группа), которому разрешён доступ.
3. При вызове API GitLab проверяет, что источник присутствует в allowlist целевого проекта.

### Fine-grained Permissions для CI_JOB_TOKEN

С версии 18.3 можно ограничить права `CI_JOB_TOKEN` конкретными разрешениями вместо полного scope проекта. Это снижает риск компрометации при утечке токена.

### Защита от fork-атак

Protected runners гарантируют, что `CI_JOB_TOKEN` с доступом к секретам не будет выдан в job, запущенный из fork-проекта или неподписанного MR. Защищённые переменные (`protected: true`) доступны только на защищённых ветках/тегах.

## Практические сценарии

### Сценарий 1: Аудит утечек CI_JOB_TOKEN

**Поиск утечек в логах:**
```bash
# Поиск CI_JOB_TOKEN в логах всех jobs
gitlab-rails runner "
  Job.all.each do |job|
    if job.trace.include?('CI_JOB_TOKEN')
      puts \"Leak in job #{job.id}: #{job.project.full_path}\"
    end
  end
"
```

**Поиск утечек в артефактах:**
```bash
# Поиск CI_JOB_TOKEN в артефактах
gitlab-rails runner "
  Ci::JobArtifact.all.each do |artifact|
    if artifact.file.content.include?('CI_JOB_TOKEN')
      puts \"Leak in artifact #{artifact.id}: #{artifact.job_id}\"
    end
  end
"
```

**Аудит токенов проекта:**
```bash
# Список Project Access Token'ов
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/access_tokens" | jq

# Список Deploy Token'ов
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/deploy_tokens" | jq
```

### Сценарий 2: Восстановление доступа после сброса allowlist

```bash
# Проверка текущих allowed проектов
curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/access_tokens" | jq

# Добавление проекта в allowlist через API (требуется Maintainer)
curl --request POST \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"source_project_id": 12345}' \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/access_requests/allowed"
```

### Сценарий 3: Миграция с CI_JOB_TOKEN на краткоживущий токен без статических секретов

**Проблема:** CI_JOB_TOKEN имеет широкий scope проекта, живёт в рамках job, требует allowlist для межпроектных вызовов.

**Решение:** Использование `id_tokens` для получения краткоживущего JWT без передачи статических секретов.

```yaml
# Было (CI_JOB_TOKEN)
deploy:
  stage: deploy
  script:
    - curl -H "JOB-TOKEN: $CI_JOB_TOKEN" https://gitlab.example.com/api/v4/projects/123/trigger/pipeline

# Стало (id_tokens)
deploy:
  stage: deploy
  id_tokens:
    GITLAB_ID_TOKEN:
      aud: https://gitlab.example.com
  script:
    - curl -H "Authorization: Bearer $GITLAB_ID_TOKEN" https://gitlab.example.com/api/v4/projects/123/trigger/pipeline
```

### Сценарий 4: Автоматический поиск и ротация скомпрометированных токенов

```bash
# 1. Отзыв всех Project Access Tokens при инциденте
for token_id in $(curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/access_tokens" | jq -r '.[].id'); do
  curl --request DELETE \
    --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
    "$CI_API_V4_URL/projects/$CI_PROJECT_ID/access_tokens/$token_id"
done

# 2. Сброс inbound allowlist
curl --request PUT \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"ci_job_token_scope_enabled": true, "ci_job_token_scope_allowlist": []}' \
  "$CI_API_V4_URL/application/settings"

# 3. Принудительный перезапуск пайплайнов с новым allowlist
curl --request POST \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/trigger/pipeline" \
  --data "token=$CI_JOB_TOKEN&ref=main"
```

## Валидация и диагностика

### Проверка статуса allowlist и настроек токена

```bash
# Проверка, включен ли enforce allowlist (self-managed)
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/application/settings" | jq '.ci_job_token_scope_enabled'

# Ожидаемое значение: true
```

### Проверка inbound allowlist проекта

```bash
# Получение списка разрешённых проектов/групп
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/access_requests/allowed" | jq

# Проверка конкретного проекта в allowlist
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/access_requests/allowed" | \
  jq --arg source_id "12345" '.[] | select(.source_project_id == ($source_id | tonumber))'
```

### Проверка masked/protected статуса переменных

```bash
# Список переменных проекта с проверкой masked/protected флагов
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/variables" | jq '.[] | {key, masked, protected, variable_type}'
```

### Аудит использования CI_JOB_TOKEN через audit events

```bash
# Поиск событий использования JOB-TOKEN (требуется admin)
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/audit_events?entity_type=Project&entity_id=$CI_PROJECT_ID&action=ci_token_used" | jq

# Поиск межпроектных вызовов
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/audit_events?entity_type=Project&entity_id=$CI_PROJECT_ID&action=cross_project_token_access" | jq
```

### Проверка protectected runners

```bash
# Список раннеров проекта с проверкой флага protected
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/runners" | jq '.[] | {id, description, protected, status}'
```

### Сканирование артефактов на утечки

```bash
# Поиск CI_JOB_TOKEN в последних артефактах проекта
gitlab-rails runner "
  Ci::JobArtifact.where(project_id: $CI_PROJECT_ID).order(id: :desc).limit(50).each do |artifact|
    begin
      content = artifact.file.read
      if content.include?('CI_JOB_TOKEN') || content.include?('JOB-TOKEN')
        puts \"Leak in artifact #{artifact.id}: job #{artifact.job_id}\"
      end
    rescue
      # skip unreadable artifacts
    end
  end
"
```

## Граничные случае и ограничения

### GitLab.com vs self-managed

| Аспект | GitLab.com | Self-managed |
| :--- | :--- | :--- |
| **Allowlist enforcement** | Обязателен для всех проектов | Зависит от `gitlab.rb` |
| **Audit events retention** | Ограничен тарифным планом | Зависит от конфигурации PostgreSQL |
| **Fine-grained Permissions** | Доступен на Premium/Ultimate | Доступен в Enterprise Edition |
| **Rate limits** | Зависят от тарифа (Free/Premium/Ultimate) | Настраиваются администратором |

### Fork-проекты и protected runners

- В fork-проекте `CI_JOB_TOKEN` автоматически блокируется для доступа к upstream-секретам, если upstream-проект использует protected runners.
- Если protected runners не настроены, fork-проект получает доступ ко всем переменным upstream-проекта, включая `CI_JOB_TOKEN`.
- Злоумышленник может создать MR в fork и получить лог job с токеном, если не включены `protected: true` и `masked: true`.

### Жизненный цикл и экспирация

- `CI_JOB_TOKEN` существует только в течение выполнения job. После завершения job токен автоматически отзывается.
- Project/Group Access Tokens могут иметь долгий TTL — ротация обязательна.
- Deploy Tokens не имеют expiry по умолчанию — требуют ручного отзыва.

### Cross-project вызовы

- Межпроектные вызовы через `CI_JOB_TOKEN` требуют inbound allowlist (18.0+).
- Внутри одного проекта allowlist не требуется.
- Cross-project вызовы учитываются в аудит-логах отдельно от внутрипроектных.

### CI_JOB_TOKEN и Container Registry

- `CI_JOB_TOKEN` может использоваться для `docker login` в Container Registry того же проекта.
- Для cross-project registry access требуется Project Access Token с scope `write_registry`.
- GitLab 18.4+ позволяет выполнять `git push` через `CI_JOB_TOKEN` в текущий репозиторий.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` при API-вызове | CI_JOB_TOKEN не в inbound allowlist | Добавьте проект в allowlist (`Settings → CI/CD → Token Access`) |
| `403 Forbidden` при registry push | CI_JOB_TOKEN не имеет scope `write_registry` | Используйте Project Access Token с нужным scope |
| Токен в логах | Job выводит переменную в лог | Установите `masked: true` и `protected: true` |
| Cross-project вызовы не работают | Allowlist сброшен или не настроен | Проверьте `Settings → CI/CD → Token Access` |
| Утечка в артефакте | Токен сохранён в файле, который архивируется | Добавьте файл в `.gitlabignore` или `artifacts:exclude` |
| Fork получает доступ к секретам | Protected runners не настроены | Включите protected runners в проекте |
| `CI_JOB_TOKEN` 403 Forbidden | Целевой проект не добавлен в Inbound Allowlist | Добавьте источник в `Settings → CI/CD → Token Access` |
| Аудит-события не генерируются | Audit logging отключён на инстансе | Включите `audit_events` в `gitlab.rb` (self-managed) |

## Best Practices

### Разработка (Dev)

1. **Никогда не выводите токены в логи:** Используйте `masked: true` и `protected: true` для всех секретов.
2. **Не передавайте CI_JOB_TOKEN наружу:** При необходимости используйте Project Access Token с ограниченным scope.
3. **Верифицируйте inbound allowlist:** После обновления GitLab проверяйте, что allowlist не сброшен.
4. **Используйте `.gitlab-ci.local.yml`:** Для локального тестирования с тестовыми токенами, не реальными.
5. **Изолируйте fork-проекты:** Настройте protected runners и отключите доступ к секретам для fork-проектов.
6. **Ограничивайте scope токена:** Используйте Fine-grained Permissions (18.3+) вместо полного scope проекта.

### Проектирование CI/CD и эксплуатация (DevOps/SRE)

1. **Включите inbound allowlist по умолчанию:** Настройте group-level policy для всех проектов.
2. **Ротируйте токены регулярно:** Project/Group Access Token'ы должны иметь срок жизни и ротироваться.
3. **Мониторьте утечки:** Настройте алерты на появление `CI_JOB_TOKEN` в логах и артефактах.
4. **Используйте краткоживущие токены:** Для новых пайплайнов предпочитайте `id_tokens` хранению долгоживущих секретов.
5. **Аудит токенов:** Регулярно проверяйте список Project/Group Access Token'ов и удаляйте неиспользуемые.
6. **Ограничьте fan-out:** При массовых триггерах downstream-пайплайнов используйте `resource_group` или последовательные стадии, чтобы избежать burst-атак на API.
7. **Мониторьте audit events:** Настройте алерты на необычные межпроектные вызовы через `CI_JOB_TOKEN` в нерабочее время.
8. **Тестируйте откат allowlist:** Периодически проверяйте, что сброс allowlist не ломает критичные пайплайны.

### Управление инстансом (Sysadmin)

1. **Ограничьте lifetime CI_JOB_TOKEN:** На уровне GitLab Server настройте TTL для `CI_JOB_TOKEN`.
2. **Включите принудительный allowlist:** Настройка `gitlab_rails['ci_job_token_scope_enabled'] = true` в `gitlab.rb`.
3. **Включите audit logging:** Включите аудит межпроектных вызовов через `CI_JOB_TOKEN`.
4. **Сетевой контроль:** Ограничьте исходящий трафик от Runner'ов до необходимых доменов.
5. **Настройте алерты на Sidekiq:** Мониторьте очередь `pipeline_hooks` на аномально высокую активность — признак массовых межпроектных вызовов.
6. **Резервное копирование allowlist:** Регулярно экспортируйте конфигурацию allowlist для восстановления после сбоев.

## Дополнительная информация

### См. также

- **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — общие принципы защиты CI/CD
- **[Переменные и секреты GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — иерархия переменных, Fine-grained Permissions
- **[Внутренности пайплайнов](../Advanced/pipeline_execution_model.md)** — жизненный цикл job, `ci_job_token_scope_enabled`
- **[Downstream пайплайны: лучшие практики](../Advanced/Downstream_Pipelines/best_practices.md)** — CI_JOB_TOKEN, allowlist, ограничения
- **[API и Webhooks автоматизация](../Advanced/api_and_webhooks_automation.md)** — работа с GitLab API

### Внешние ресурсы

- [GitLab: CI_JOB_TOKEN](https://docs.gitlab.com/ee/ci/jobs/ci_job_token.html)
- [GitLab: Project Access Tokens](https://docs.gitlab.com/ee/user/project/settings/project_access_tokens.html)
