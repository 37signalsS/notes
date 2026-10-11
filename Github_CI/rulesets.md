# GitHub Rulesets: Защита веток, тегов и workflow execution

**Актуально для:** GitHub Rulesets, GitHub Enterprise Server 3.14+ / GitHub.com (REST API v3, API Version 2026-03-10; workflow execution protections — GA с сентября 2026; default pull_request_target policy — с ноября 2026)

GitHub Rulesets — современная замена устаревшему механизму **Branch Protection Rules** (BPR). Rulesets предоставляют декларативную, масштабируемую и API-дружелюбную модель защиты ссылок (веток и тегов), валидации метаданных при пуше и контроля запуска рабочих процессов CI/CD. В отличие от BPR, настраиваемых индивидуально в каждом репозитории, Rulesets функционируют на трёх уровнях иерархии (**Enterprise → Organization → Repository**) с поддержкой кумулятивного наследования, теневого аудита (Evaluate mode) и гибких списков исключений (Bypass Actors).

## Определения

- **Ruleset (Набор правил)**: Именованная конфигурационная сущность, объединяющая условия таргетинга (conditions), правила защиты (rules), уровень применения (enforcement) и перечень доверенных субъектов с правом обхода (bypass actors).
- **Target (Целевой объект)**: Область применения набора правил. Поддерживаемые типы: `branch` (ветки), `tag` (теги), `push` (валидация метаданных коммитов и содержимого файлов при отправке изменений).
- **Enforcement Status**: Статус активности правил:
  - `active` — правила строго блокируют несоответствующие операции;
  - `evaluate` — режим теневой оценки (dry-run): операции не блокируются, но факты нарушений логируются в Audit Log и отображаются в Rule Insights;
  - `disabled` — набор правил полностью отключён.
- **Bypass Actor**: Субъект (пользователь, команда, роль, GitHub App или Deploy Key), которому разрешено полностью или частично обходить правила защиты.
- **Bypass Mode**: Режим обхода правил:
  - `always` — постоянное право на обход всех ограничений набора;
  - `pull_request` — обход только требований слияния в Pull Request (создание PR остаётся обязательным, но проверки не блокируют мерж);
  - `exempt` — системное исключение без создания событий обхода в журнале аудита.
- **Branch Protection Rules (BPR)**: Устаревший механизм защиты веток на уровне отдельного репозитория без поддержки иерархического наследования, защиты тегов и push-валидаций.
- **Workflow Execution Protection**: Политика безопасности GitHub Actions, ограничивающая выполнение рабочих процессов на основе фильтрации инициаторов (actor rules) и событий (event rules), предотвращающая атаки через `pull_request_target` из непроверенных форков.
- **Merge Queue (Очередь слияния)**: Сервисный механизм GitHub, автоматически выстраивающий проверенные Pull Request в очередь для последовательной сборки и слияния временных групп коммитов, исключающий состояние гонки («semantic merge conflicts») в целевой ветке.
- **Strict Required Status Checks**: Режим обязательной актуализации ветки PR относительно базовой ветки перед слиянием, гарантирующий тестирование изменений на актуальном состоянии целевого кода.

## Архитектура и принципы работы

### Иерархия уровней и объединение правил

Rulesets функционируют по принципу вертикального наследования с кумулятивным ужесточением:

```text
Enterprise Ruleset (глобальные политики безопасности компании)
    ↓ (наследуются всеми организациями)
Organization Ruleset (политики для всех или выбранных репозиториев)
    ↓ (наследуются конкретным репозиторием)
Repository Ruleset (локальные правила проекта)
    ↓
Effective Rules (итоговый набор действующих ограничений)
```

1. **Кумулятивность (Additive principle)**: Ни один нижестоящий уровень не может отменить или ослабить правило, заданное на вышестоящем уровне. Локальные настройки репозитория могут только дополнять политики организации.
2. **Разрешение конфликтов (Strictest wins)**: Если на уровне организации требуется 2 одобряющих рецензии (`required_approving_review_count: 2`), а в репозитории настроено 1, применяется более строгое требование — 2 рецензии.
3. **Изоляция статуса Evaluate**: Если на уровне организации правило находится в статусе `evaluate`, а в репозитории аналогичное правило переведено в `active`, локальные операции будут блокироваться. Если же организация установила `active`, локальный перевод в `evaluate` не снимет блокировку.

### Таргетинг условий (Conditions и Ref Patterns)

Rulesets поддерживают таргетинг целевых ссылок через блок `conditions`:
- **Динамические ссылки**:
  - `~DEFAULT_BRANCH` — автоматически выбирает ветку по умолчанию репозитория (независимо от имени: `main`, `master` и т. д.);
  - `~ALL` — распространяется на все ветки или все теги репозитория.
- **Паттерны имен (fnmatch)**:
  - `refs/heads/release/*` — ветки релизов первого уровня (`release/v1.0`);
  - `refs/heads/feature/**` — ветки с любой глубиной вложенности;
  - `refs/tags/v*` — теги версий, начинающиеся с `v`.
- **Включения и исключения**: Правило применяется, если ссылка попадает под условие `include` и не попадает под условие `exclude`.

### Модель Bypass Actors и безопасность автоматизации

В Rulesets право обхода защиты привязано к конкретным сущностям:

| Тип актора (`actor_type`) | Значение `actor_id` | Применение |
|---|---|---|
| `Integration` | ID приложения GitHub App | Автоматизация CI/CD через App Installation Token (рекомендуемый метод) |
| `OrganizationAdmin` | `null` (игнорируется) | Все владельцы организации |
| `RepositoryRole` | `1` (Admin), `2` (Maintain), `4` (Write) | Ролевой доступ участников репозитория |
| `Team` | ID команды GitHub | Групповой доступ дежурных инженеров или SRE-команды |
| `DeployKey` | `null` | Серверный SSH-ключ развёртывания с правом записи |
| `User` | ID пользователя GitHub | Персональный доступ (не рекомендуется для CI) |

> [!IMPORTANT]
> Системный токен `GITHUB_TOKEN` рабочего процесса GitHub Actions **не может** обходить Rulesets. Токен оценивается платформой как непривилегированный агент, даже если workflow запущен администратором. Для записи в защищённые ветки или публикации защищённых тегов из конвейера автоматизации необходимо генерировать токен установки **GitHub App** (см. [github_apps.md](./github_apps.md) и [Git_Automation.md](./Git_Automation.md)) либо использовать SSH Deploy Key, внесённый в bypass-лист.

### Доступные типы правил (Rule Types)

Правила разделяются по целевым объектам (`target`):

1. **Правила для веток (`target: branch`)**:
   - `creation` — запрет создания ветки напрямую (только через bypass);
   - `update` — запрет прямого пуша коммитов; параметр `update_allows_fetch_and_merge: true` разрешает синхронизацию форков через веб-интерфейс;
   - `deletion` — запрет удаления ветки;
   - `required_linear_history` — запрет merge-коммитов (допускаются только fast-forward и rebase);
   - `required_signatures` — требование валидной криптографической подписи (GPG, SSH, S/MIME) для каждого коммита;
   - `non_fast_forward` — строгий запрет принудительной отправки (`git push --force` и `--force-with-lease`);
   - `pull_request` — требование слияния только через Pull Request:
     - `required_approving_review_count`: минимальное число аппрувов;
     - `dismiss_stale_reviews_on_push`: сброс одобрений при добавлении новых коммитов;
     - `require_code_owner_review`: обязательное одобрение владельцев файлов по файлу `CODEOWNERS`;
     - `require_last_push_approval`: запрет автору последнего пуша одобрять изменения;
     - `required_review_thread_resolution`: обязательное закрытие всех дискуссий в коде;
     - `allowed_merge_methods`: список разрешённых методов слияния (`merge`, `squash`, `rebase`);
   - `required_status_checks` — обязательные проверки CI перед слиянием:
     - `strict_required_status_checks_policy: true`: требование актуальности ветки;
     - `required_status_checks`: список пар `{context, integration_id}`;
   - `merge_queue` — принудительное прохождение через очередь слияния;
   - `required_deployments` — обязательное успешное развёртывание во внешнее окружение (staging/preprod) до слияния в ветку.

2. **Правила для тегов (`target: tag`)**:
   - `creation`, `update` (запрет перезаписи существующего тега), `deletion`, `required_signatures`.

3. **Правила уровня отправки (`target: push`)**:
   - `max_file_size` — ограничение максимального размера отдельного файла в мегабайтах;
   - `file_extension_restriction` — запрет пуша файлов с опасными расширениями (`.key`, `.pem`, `.env`, `.pfx`);
   - `file_path_restriction` — запрет пуша в защищённые каталоги;
   - `max_file_path_length` — ограничение длины пути файла;
   - `commit_message_pattern` — валидация сообщений коммитов регулярным выражением (например, Conventional Commits);
   - `commit_author_email_pattern` / `committer_email_pattern` — ограничение email авторов корпоративным доменом.

## Практические сценарии и настройка

### Сценарий 1: Комплексная защита ветки `main` через API и JSON-манифест

Создание набора правил для ветки по умолчанию с блокировкой force-push, обязательной линейной историей, проверкой подписей, строгим CI и допуском бота релизов через GitHub App.

**Файл манифеста `ruleset-main.json`:**
```json
{
  "name": "Production Main Protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": [
        "~DEFAULT_BRANCH"
      ],
      "exclude": []
    }
  },
  "bypass_actors": [
    {
      "actor_id": 894120,
      "actor_type": "Integration",
      "bypass_mode": "always"
    },
    {
      "actor_id": 1,
      "actor_type": "RepositoryRole",
      "bypass_mode": "pull_request"
    }
  ],
  "rules": [
    {
      "type": "deletion"
    },
    {
      "type": "non_fast_forward"
    },
    {
      "type": "required_linear_history"
    },
    {
      "type": "required_signatures"
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 2,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "require_last_push_approval": true,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": [
          "squash",
          "rebase"
        ]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          {
            "context": "test / unit-integration"
          },
          {
            "context": "security / static-analysis"
          }
        ]
      }
    }
  ]
}
```

**Применение через GitHub CLI:**
```bash
gh api --method POST /repos/{owner}/{repo}/rulesets \
  --input ruleset-main.json \
  --jq '{id: .id, name: .name, enforcement: .enforcement}'
# → {"id": 481920, "name": "Production Main Protection", "enforcement": "active"}
```

**Проверка работы:**
```bash
# Попытка прямого пуша в main разработчиком без прав bypass
git push origin main
# → To github.com:company/app.git
# →  ! [remote rejected] main -> main (push declined due to repository rule violations)
# → error: failed to push some refs to 'github.com:company/app.git'
# → remote: error: GH013: Repository rule violations found for refs/heads/main.
# → remote: Review 'Production Main Protection' ruleset requirements.
```

### Сценарий 2: Защита релизных тегов (`refs/tags/v*`)

Защита immutable-тегов версий от случайного удаления или перемещения на другой коммит.

**Файл манифеста `ruleset-tags.json`:**
```json
{
  "name": "Immutable Release Tags",
  "target": "tag",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": [
        "refs/tags/v*"
      ],
      "exclude": []
    }
  },
  "bypass_actors": [
    {
      "actor_id": 894120,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ],
  "rules": [
    {
      "type": "creation"
    },
    {
      "type": "update"
    },
    {
      "type": "deletion"
    },
    {
      "type": "required_signatures"
    }
  ]
}
```

**Применение:**
```bash
gh api --method POST /repos/{owner}/{repo}/rulesets --input ruleset-tags.json \
  --jq '{id: .id, name: .name, target: .target}'
# → {"id": 481921, "name": "Immutable Release Tags", "target": "tag"}
```

### Сценарий 3: Валидация коммитов и блокировка утечек секретов на уровне Push

Правила с типом `target: push` применяются на этапе выполнения `git-receive-pack` до фиксации объектов в Git ODB.

**Файл манифеста `ruleset-push-policy.json`:**
```json
{
  "name": "Push Metadata and File Restrictions",
  "target": "push",
  "enforcement": "active",
  "rules": [
    {
      "type": "file_extension_restriction",
      "parameters": {
        "restricted_file_extensions": [
          "key",
          "pem",
          "pfx",
          "crt",
          "env"
        ]
      }
    },
    {
      "type": "max_file_size",
      "parameters": {
        "max_file_size": 50
      }
    },
    {
      "type": "commit_message_pattern",
      "parameters": {
        "name": "Conventional Commits Enforcement",
        "operator": "regex",
        "pattern": "^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\\([a-z0-9_-]+\\))?: .+",
        "negate": false
      }
    },
    {
      "type": "commit_author_email_pattern",
      "parameters": {
        "name": "Corporate Email Only",
        "operator": "regex",
        "pattern": ".*@company\\.internal$",
        "negate": false
      }
    }
  ]
}
```

**Применение:**
```bash
gh api --method POST /repos/{owner}/{repo}/rulesets --input ruleset-push-policy.json \
  --jq '{id: .id, name: .name, target: .target, enforcement: .enforcement}'
# → {"id": 481922, "name": "Push Metadata and File Restrictions", "target": "push", "enforcement": "active"}
```

**Тестирование отклонения пуша:**
```bash
# Попытка закоммитить файл с недопустимым расширением
touch private.pem && git add private.pem && git commit -m "chore: add cert"
git push origin feature/test-auth
# → remote: error: GH013: Repository rule violations found.
# → remote: - Changes must not contain restricted file extensions: key, pem, pfx, crt, env. Found: private.pem
# → To github.com:company/app.git
# →  ! [remote rejected] feature/test-auth -> feature/test-auth (push declined due to repository rule violations)
```

### Сценарий 4: Организационный Ruleset в режиме Evaluate (Gradual Rollout)

Перед введением строгих политик на сотни репозиториев организации используется статус `evaluate` для сбора статистики без блокировки работы инженеров.

```bash
# Создание ruleset на уровне организации в режиме evaluate
gh api --method POST /orgs/{org}/rulesets \
  --input - <<'EOF'
{
  "name": "Org Baseline: Linear History and Review",
  "target": "branch",
  "enforcement": "evaluate",
  "conditions": {
    "ref_name": {
      "include": [
        "~DEFAULT_BRANCH"
      ],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "required_linear_history"
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": [
          "squash",
          "rebase"
        ]
      }
    }
  ]
}
EOF
# → {"id": 91823, "name": "Org Baseline: Linear History and Review", "enforcement": "evaluate"}
```

### Сценарий 5: Интеграция с Merge Queue

Для репозиториев с частыми слияниями и интенсивным потоком коммитов активируется правило `merge_queue`:

```json
{
  "name": "Trunk Merge Queue Protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": [
        "refs/heads/main"
      ],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "merge_queue",
      "parameters": {
        "check_response_timeout_minutes": 60,
        "grouping_strategy": "ALLGREEN",
        "max_entries_to_build": 5,
        "max_entries_to_merge": 10,
        "min_entries_to_merge": 1,
        "min_entries_to_merge_wait_minutes": 5,
        "merge_method": "SQUASH"
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          {
            "context": "build-and-test"
          }
        ]
      }
    }
  ]
}
```

- `grouping_strategy: ALLGREEN`: Каждый промежуточный коммит внутри сформированной пачки (batch) обязан успешно пройти CI. В отличие от `HEADGREEN` (где проверяется только вершина пачки), `ALLGREEN` предотвращает поломку бисекции (`git bisect`) при последующем аудите истории.

### Сценарий 6: Workflow Execution Protections (контроль запуска Actions)

Ограничение прав на выполнение рабочих процессов CI на уровне организации или репозитория.

1. **Actor Allowlist**: Ограничивает перечень учетных записей, имеющих право инициировать рабочие процессы (например, участники организации, команда `platform-sre` и проверенные интеграции вроде Dependabot).
2. **Event Filtering**: Разрешение запуска только для событий `push`, `pull_request` (из доверенных веток) и `workflow_dispatch`.
3. **Default Policy для `pull_request_target`**: С ноября 2026 платформа блокирует автоматический запуск `pull_request_target` для внешних форков и недоверенных участников, защищая секреты репозитория от внедрения вредоносного кода через PR (подробнее см. [Core_Concept.md](./Core_Concept.md)).

## Операции и команды CLI/API

### Сводная таблица API Endpoints

| Назначение | HTTP Метод и Endpoint | Описание |
|---|---|---|
| Список rulesets репозитория | `GET /repos/{owner}/{repo}/rulesets` | Возвращает локальные и (опционально) унаследованные правила |
| Создать ruleset репозитория | `POST /repos/{owner}/{repo}/rulesets` | Создание локального набора правил |
| Получить конкретный ruleset | `GET /repos/{owner}/{repo}/rulesets/{ruleset_id}` | Детальная конфигурация набора |
| Обновить ruleset | `PATCH /repos/{owner}/{repo}/rulesets/{ruleset_id}` | Изменение правил или статуса (`enforcement`) |
| Удалить ruleset | `DELETE /repos/{owner}/{repo}/rulesets/{ruleset_id}` | Полное удаление набора правил |
| Проверить эффективные правила | `GET /repos/{owner}/{repo}/rules/branches/{branch}` | Список всех активных правил, действующих на ветку |
| Rulesets организации | `GET/POST /orgs/{org}/rulesets` | Управление правилами уровня организации |
| Rulesets предприятия | `GET/POST /enterprises/{enterprise}/rulesets` | Управление политиками Enterprise |

### Примеры команд GitHub CLI

```bash
# 1. Просмотр списка rulesets с фильтрацией по имени и статусу
gh api /repos/{owner}/{repo}/rulesets --jq '.[] | {id: .id, name: .name, target: .target, enforcement: .enforcement, source: .source_type}'
# → {"id": 481920, "name": "Production Main Protection", "target": "branch", "enforcement": "active", "source": "Repository"}
# → {"id": 91823, "name": "Org Baseline: Linear History", "target": "branch", "enforcement": "evaluate", "source": "Organization"}

# 2. Получение списка всех эффективных правил для конкретной ветки
gh api /repos/{owner}/{repo}/rules/branches/main --jq '.[].type'
# → deletion
# → non_fast_forward
# → required_linear_history
# → required_signatures
# → pull_request
# → required_status_checks

# 3. Экспорт конфигурации набора правил в файл для резервного копирования или GitOps
gh api /repos/{owner}/{repo}/rulesets/481920 > ruleset_backup.json

# 4. Переключение ruleset из режима evaluate в active
gh api --method PATCH /repos/{owner}/{repo}/rulesets/481920 \
  -f enforcement="active" \
  --jq '{id: .id, enforcement: .enforcement}'
# → {"id": 481920, "enforcement": "active"}

# 5. Проверка истории срабатываний правил в Audit Log
gh api "/orgs/{org}/audit-log?phrase=action:repo.ruleset_evaluated" \
  --jq '.[] | {actor: .actor, repo: .repo, rule_evaluation: .rule_evaluation_result}'
# → {"actor": "developer1", "repo": "company/app", "rule_evaluation": "pass"}
# → {"actor": "bot-service", "repo": "company/app", "rule_evaluation": "fail"}
```

## Устранение неполадок

| Проблема / Ошибка | Первопричина | Диагностика | Решение |
|---|---|---|---|
| `remote: error: GH013: Repository rule violations found` | Попытка прямого пуша в защищённую ветку или нарушение условий (линейная история, подпись коммита) | `gh api /repos/{owner}/{repo}/rules/branches/{branch}` | Создать Pull Request; перебазировать коммиты (`git rebase -i`); подписать коммит (`git commit -S --amend`). |
| `Changes must be made through a pull request` | В ruleset включено правило `pull_request`, а субъект не входит в `bypass_actors` | Проверить секцию `bypass_actors` в конфигурации ruleset | Выполнять изменение через PR либо добавить сервисный аккаунт (GitHub App) в bypass-лист. |
| CI-конвейер падает с `403 Resource not accessible by integration` при пуше тега | `GITHUB_TOKEN` не может обходить ruleset даже с `permissions: contents: write` | Проверить аутентификацию в workflow: используется ли стандартный токен | Использовать GitHub App Installation Token через `actions/create-github-app-token` с правами `contents: write`. |
| `Commit signature required but not found` | Включено правило `required_signatures`, но коммит сделан без GPG/SSH подписи | `git log --show-signature -1` | Настроить подпись: `git config user.signingkey <KEY_ID>`, `git commit -S --amend --no-edit`, повторить push. |
| Ожидание статус-чека зависает: `Expected — Waiting for status to be reported` | Контекст проверки в ruleset не совпадает с реальным именем джобы CI или workflow не запустился | Сравнить имя в `required_status_checks` с именем job в логах Actions | Уточнить имя шага/джобы в `.github/workflows/` (например, `job_name` вместо имени workflow). |
| Ruleset переведён в `evaluate`, но пуш всё равно блокируется | Действует унаследованный ruleset уровня Organization или Enterprise со статусом `active` | `gh api "/repos/{owner}/{repo}/rulesets?includes_parents=true"` | Проверить родительские наборы правил (`source_type: Organization`). Изменить правила на уровне организации. |
| Merge Queue сбрасывает PR с ошибкой таймаута | Время выполнения проверок CI превысило лимит `check_response_timeout_minutes` | Проверить время сборки джоб в Actions | Увеличить таймаут в конфигурации правила `merge_queue` или оптимизировать кеширование и параллелизм CI. |
| Запрет создания ветки: `Cannot create ref: rule violation` | Включено правило `creation` для шаблона веток без прав bypass | Проверить условия `conditions.ref_name` | Убедиться, что имя новой ветки соответствует разрешённым паттернам разработчиков (`feature/*`, `fix/*`). |

## Лучшие практики

1. **GitOps-управление политиками (Rulesets as Code)**:
   - Не настраивайте правила вручную через веб-интерфейс. Храните JSON/YAML манифесты правил в репозитории платформенной инфраструктуры.
   - Автоматизируйте применение через GitHub CLI или Terraform/OpenTofu (`github_repository_ruleset`, `github_organization_ruleset`).
2. **Многоступенчатый ввод правил через Evaluate Mode**:
   - Любое новое ограничение должно находиться в статусе `evaluate` не менее 7–14 дней.
   - Анализируйте данные в разделе **Insights → Rules** и Audit Log для обнаружения легитимных рабочих процессов, которые могут сломаться при включении `active`.
3. **Строгая изоляция автоматизации (Zero Trust к токенам)**:
   - Никогда не используйте персональные токены сотрудников (PAT) для обхода правил в CI/CD.
   - Добавляйте в bypass-лист исключительно **GitHub Apps** (тип `Integration`). Это даёт гранулярные скоупы, ограниченное время жизни токена (1 час) и строгую атрибуцию в журналах аудита.
4. **Отказ от BPR в пользу Rulesets**:
   - Перенесите устаревшие Branch Protection Rules на Rulesets. Rulesets работают быстрее, поддерживают таргетинг по паттернам тегов, валидацию push-метаданных и не конфликтуют при масштабировании.
5. **Слоистая модель защиты**:
   - **Enterprise**: запрет удаления веток, запрет force-push, глобальные ограничения размера файлов.
   - **Organization**: базовые требования к транк-ветке (`~DEFAULT_BRANCH`): Pull Request, минимум 1 рецензия, линейная история.
   - **Repository**: проектные проверки (специфичные контексты CI, среды `required_deployments`, списки CODEOWNERS).
6. **Защита неизменяемости релизов (Immutable Tags)**:
   - Паттерн `refs/tags/v*` должен быть защищён от обновления (`update`), удаления (`deletion`) и создания непроверенными акторами. Релизные артефакты не должны перезаписываться в Git-дереве.
7. **Использование Merge Queue для высоконагруженных проектов**:
   - Внедряйте `merge_queue` вместе со строгими статус-чеками (`strict_required_status_checks_policy`). Это исключает ситуацию, когда два одновременно прошедших проверку PR ломают основную ветку при слиянии.

## Дополнительная информация

- **[Git-автоматизация](./Git_Automation.md)** — безопасный пуш из Actions через App-токен, bypass правил и бот-коммиты.
- **[GitHub Apps](./github_apps.md)** — регистрация приложения GitHub App и настройка его прав в качестве Bypass Actor.
- **[Управление релизами](./Release_Management.md)** — автоматизация версионирования и защита релизных тегов.
- **[Ключевые концепции GitHub CI](./Core_Concept.md)** — матрица прав токенов, безопасность Pull Requests и workflow execution protections.
- **[Рабочие процессы Git](../Git/git_workflows.md#защита-веток-branch-protection)** — методология защиты веток в Trunk-Based Development и Git Flow.
- **[GitHub CLI](./github_cli.md)** — управление репозиториями, Pull Requests и вызовами REST API через CLI `gh`.
