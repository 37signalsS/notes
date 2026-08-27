# Монорепо CI для фронтенда (Turborepo / Nx)

## Определения

- **Монорепо (Monorepo)** — единый репозиторий, содержащий несколько приложений и библиотек фронтенда (и не только).
- **Turborepo / Nx** — инструменты оркестрации задач в монорепо с кэшированием и графом зависимостей.
- **Affected builds** — сборка/тест только тех проектов, которые реально изменились (и их зависимостей) относительно базовой ветки.
- **Remote / Distributed Cache** — разделяемое между раннерами хранилище кэша задач (результаты сборки/тестов переиспользуются).
- **Task Graph** — направленный граф задач (build, test, lint) с зависимостями между проектами.
- **Filter** — селектор проекта/задачи (например, только `app-checkout`).

---

## Основные концепции

### Зачем нужен CI для монорепо
Без оптимизаций пайплайн собирает и тестит ВСЁ при каждом пуше — это медленно и дорого. Ключевые приёмы:
- **Affected:** запускать задачи только для изменённых проектов.
- **Кэш задач:** переиспользовать результаты идентичных задач (по хэшу входов) между прогонами и раннерами.
- **Параллелизм:** распределять независимые задачи по агентам.

### Remote cache без облака
Хранилище кэша можно держать on-prem: Turborepo поддерживает S3-совместимый бакет (MinIO), Nx — свой сервер кэша (Nx Cloud self-hosted или собственный `nx-cloud`). Это ускоряет CI без привязки к облачному вендору.

### Версии и зависимые деплои
В монорепо одна библиотека может использоваться многими приложениями. Affected-анализ должен учитывать не только прямые, но и транзитивные зависимости, чтобы деплой затронул все затронутые приложения.

---

## Практические сценарии

### Сценарий 1: Affected-сборка и тесты (Turborepo)
```bash
# Только затронутые проекты относительно main
npx turbo run build test lint --filter=...[origin/main]
# Конкретное приложение и его зависимости
npx turbo run build --filter=app-checkout...
```

### Сценарий 2: Remote cache на on-prem S3-совместимом хранилище
```bash
# Turbo: переменные окружения указывают на MinIO/S3
export TURBO_REMOTE_CACHE_SIGNATURE_KEY=***          # подпись кэша (целостность)
export AWS_ACCESS_KEY_ID=$MINIO_KEY
export AWS_SECRET_ACCESS_KEY=$MINIO_SECRET
npx turbo run build --remote-only                     # читать/писать в remote cache
```
```yaml
# GitLab CI: кэш задач по хэшу lock-файла
build_monorepo:
  cache:
    key: { files: [package-lock.json, turbo.json] }
    paths: [node_modules/, .turbo/]
  script:
    - npx turbo run build --filter=...[origin/main] --remote-only
```

### Сценарий 3: Параллельные джобы по приложениям
```yaml
# Генерируем матрицу приложений и деплоим только изменённые
deploy_apps:
  strategy:
    matrix:
      app: [app-checkout, app-catalog, app-profile]
  script:
    - npx turbo run deploy --filter=$APP... --filter=...[origin/main]
```

### Сценарий 4: Условный деплой только изменённых приложений
```bash
# Список затронутых проектов
APPS=$(npx turbo run build --filter=...[origin/main] --dry=json | jq -r '.tasks[].package')
for app in $APPS; do
  echo "Deploying $app"
  npx turbo run deploy --filter=$app
done
```

---

## Дополнительная информация

### Лучшие практики
1. Всегда используйте `--filter=...[origin/main]` для affected-анализа, иначе CI соберёт весь репозиторий.
2. Включайте remote cache с подписью (`TURBO_REMOTE_CACHE_SIGNATURE_KEY`) — иначе кэш можно отравить.
3. Кэшируйте `node_modules` и `.turbo` по хэшу `package-lock.json` + `turbo.json`.
4. Деплой запускайте только для приложений, попавших в affected-выборку.
5. Фиксируйте версию Node.js в `.nvmrc` и используйте тот же образ в CI.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| CI собирает всё подряд | Нет affected-фильтра | `--filter=...[origin/main]` |
| Кэш не переиспользуется | Разные раннеры без remote cache | Настроить remote cache (S3/MinIO) |
| Отравление кэша | Нет подписи кэша | `TURBO_REMOTE_CACHE_SIGNATURE_KEY` |
| Пропущен деплой зависимого приложения | Только прямые зависимости | Использовать `...` (включает транзитивные) |

### См. также
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — кэширование зависимостей и воспроизводимая сборка.
- **[Микро-фронтенды и Module Federation](./micro_frontends_cicd.md)** — когда микро-фронтенды живут в одном монорепо.
- **[Ключи кэша и политики в GitLab CI](../GitLab_CI/Advanced/gitlab_ci_caching/cache_keys.md)** — кэширование в CI.
- **[Управление пулом раннеров](../runner-fleet-management.md)** — параллелизм задач.
