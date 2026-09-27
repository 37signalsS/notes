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

### Требования к окружению

Для настройки CI монорепо с Turborepo или Nx необходимы:
- **Node.js LTS:** фиксированная версия в `.nvmrc` / `engines` поля `package.json`, идентичная в CI и на машинах разработчиков. Разные минорные версии меняют хэш зависимостей и ломают remote cache.
- **Turborepo или Nx:** выбранный инструмент оркестрации задач, установленный как devDependency. Переключение между ними требует пересборки всего графа.
- **CI-система:** GitLab CI, GitHub Actions или аналогичная, поддерживающая матричные стратегии, `needs` / DAG и переменные окружения.
- **Хранилище артефактов / remote cache:** on-prem S3-совмимый бакет (MinIO, Ceph RGW, Nexus) для Turborepo или self-hosted Nx cache server. Ключ доступа должен храниться в секретах CI, а не в репозитории.
- **Подпись remote cache:** секретный ключ (`TURBO_REMOTE_CACHE_SIGNATURE_KEY`), предотвращающий отравление кэша посторонними результатами.
- **Git с shallow clone:** включён `GIT_DEPTH` для ускорения clone, но достаточно глубокий для корректного affected-анализа относительно базовой ветки.
- **Runtime-конфигурация deploy:** механизм передачи URL артефактов/версий из CI в среду (environment variables, feature flag service, конфиг-сервис).

---

### Сценарий 1: Affected-сборка и тесты (Turborepo)
```bash
# Только затронутые проекты относительно main
npx turbo run build test lint --filter=...[origin/main]
# Конкретное приложение и его зависимости
npx turbo run build --filter=app-checkout...
```
# → запущены задачи только для проектов, у которых есть изменения в `changeset` относительно `origin/main`

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
# → при совпадении хэша входов задачи берутся из remote cache; при изменении lock-файла кэш пересобирается

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
# → джобы запускаются параллельно только для apps, попавших в affected-выборку; остальные пропускаются

### Сценарий 4: Условный деплой только изменённых приложений
```bash
# Список затронутых проектов
APPS=$(npx turbo run build --filter=...[origin/main] --dry=json | jq -r '.tasks[].package')
for app in $APPS; do
  echo "Deploying $app"
  npx turbo run deploy --filter=$app
done
```
# → деплоятся только затронутые приложения + их транзитивные зависимости; неизменённые пропущены

---

## Дополнительная информация

### Лучшие практики
1. Всегда используйте `--filter=...[origin/main]` для affected-анализа, иначе CI соберёт весь репозиторий.
2. Включайте remote cache с подписью (`TURBO_REMOTE_CACHE_SIGNATURE_KEY`) — иначе кэш можно отравить.
3. Кэшируйте `node_modules` и `.turbo` по хэшу `package-lock.json` + `turbo.json`.
4. Деплой запускайте только для приложений, попавших в affected-выборку.
5. Фиксируйте версию Node.js в `.nvmrc` и используйте тот же образ в CI.
6. Для Nx используйте `nx affected` с явным `--base=origin/main` — по умолчанию Nx сравнивает с предыдущим коммитом, что даёт ложный affected при force-push.
7. Ограничивайте параллельные джобы через `concurrency` в CI, чтобы не перегружать раннеры и внешние сервисы (artifact registry, CDN).
8. Храните remote cache на on-prem/MinIO с retention policy (например, 7–30 дней), чтобы лимиты S3 не росли бесконечно.
9. Для больших монорепо (>50 пакетов) используйте parent-child пайплайны: дочерний пайплайн получает список затронутых проектов и запускает задачи только для них. Детали — в **[Родительско-дочерние пайплайны](../GitLab_CI/Advanced/Downstream_Pipelines/parent_child_pipelines.md)**.
10. Изолируйте cache hit/miss метрики и alert на падение hit rate < 80% — это означает либо сломанный remote cache, либо отравление подписью.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| CI собирает всё подряд | Нет affected-фильтра | `--filter=...[origin/main]` |
| Кэш не переиспользуется | Разные раннеры без remote cache | Настроить remote cache (S3/MinIO) |
| Отравление кэша | Нет подписи кэша | `TURBO_REMOTE_CACHE_SIGNATURE_KEY` |
| Пропущен деплой зависимого приложения | Только прямые зависимости | Использовать `...` (включает транзитивные) |
| `nx affected` не видит изменения | Сравнение с предыдущим коммитом, а не с main | `nx affected --base=origin/main` |
| Remote cache miss при каждом запуске | Неверный ключ/доступ к MinIO, разная Node версия | Проверить credentials, фиксировать Node в `.nvmrc` |
| Gitaly timeout при создании pipeline | Слишком много lock-файлов в `cache:key:files` | Использовать статический ключ или якоря YAML (детали в `cache_keys.md`) |
| Затронутый проект не попал в матрицу deploy | Неверный filter, отсутствие `...` | Проверить dry-run: `turbo run deploy --filter=...[origin/main] --dry=json` |

### Валидация CI
- **Affected detection:** после настройки запустите `turbo run build --filter=...[origin/main] --dry=json` и убедитесь, что список затронутых пакетов соответствует реальным изменениям.
- **Remote cache hit rate:** в отчёте Turborepo есть поле `FULL TURBO` / `FULL TURBO REMOTE` — hit rate должен быть >80% для стабильного репозитория.
- **Cache integrity:** после настройки `TURBO_REMOTE_CACHE_SIGNATURE_KEY` убедитесь, что при передаче кэша между раннерами не возникает `Signature verification failed`.
- **Deploy list validation:** перед деплоем запустите dry-run и проверьте, что в списке нет неизменённых приложений.
- **Node version drift:** в CI добавьте `node --version` в логи и сравните с `.nvmrc`; расхождение ломает reproducibility.

### Особые случаи

- **Большой монорепо (>50 пакетов):** affected-анализ и граф задач могут занимать десятки секунд. Используйте parent-child пайплайны: родительский пайплайн вычисляет affected-список, дочерний получает его через trigger и выполняет задачи. Это ускоряет pipeline creation и не перегружает CI-сервер.
- **Force-push в main:** affected-анализ относительно `origin/main` даёт корректный результат только при линейной истории. При force-push используйте merge-base или защищайте ветку политикой `no force push`.
- **Circular dependencies между пакетами:** Turborepo/Nx обнаружат цикл в графе, но CI упадёт с неочевидной ошибкой. Используйте `turbo run build --graph` или `nx graph` для визуализации и поиска циклов.
- **Миграция с Nx на Turborepo (или наоборот):** оба инструмента используют lock-файл (`turbo.json` / `project.json`), но формат кэша несовместим. Планируйте миграцию как полный invalidate remote cache, иначе будут ghost-builds из старого формата.
- **Cache key collision при частом обновлении lock-файла:** если `package-lock.json` меняется в каждом пуше (например, через `npm audit`), remote cache не переиспользуется. Используйте отдельный lock-файл для CI или отключайте автоматические обновления audit в пайплайне.
- **Ephemeral runners и remote cache:** при использовании эфемерных раннеров локальный `.turbo`/`.nx/cache` не сохраняется между джобами, поэтому remote cache обязателен. Без него каждый пуше собирает всё с нуля.
- **Dependency hoisting в pnpm/workspace:** hoisting меняет структуру `node_modules`, что влияет на хэш задачи. Фиксируйте workspace Protocol (`"node_modules"` в pnpm) или используйте одинаковый менеджер пакетов во всех проектах монорепо.

### См. также
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — кэширование зависимостей, воспроизводимая сборка, изоляция окружения.
- **[Микро-фронтенды и Module Federation](./micro_frontends_cicd.md)** — когда микро-фронтенды живут в одном монорепо.
- **[Ключи кэша и политики в GitLab CI](../GitLab_CI/Advanced/gitlab_ci_caching/cache_keys.md)** — детали конфигурации кэша в GitLab CI, Gitaly limits.
- **[Родительско-дочерние пайплайны](../GitLab_CI/Advanced/Downstream_Pipelines/parent_child_pipelines.md)** — DAG, trigger, наследование переменных.
- **[CI platform engineering](./frontend_ci_platform_engineering.md)** — self-hosted runners, runner scaling, DAG optimization.
