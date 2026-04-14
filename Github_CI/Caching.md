# GitHub Actions: Кеширование

Кеширование — один из самых эффективных способов ускорить выполнения CI/CD пайплайнов в GitHub Actions. Его основная цель — сохранять файлы (например, зависимости или результаты сборки) между запусками воркфлоу, чтобы избежать их повторного скачивания или генерации.

## Определения

- **Кеш (Cache)**: Хранилище, привязанное к репозиторию, в котором можно сохранять файлы и директории. Доступ к кешу осуществляется по уникальному ключу.
- **`actions/cache`**: Официальный `action` от GitHub для работы с кешем. Текущая версия — `v5.0.4` (март 2026). Рекомендуется использовать `@v4` или `@v5` для стабильности.
- **Cache Service v2**: Переписанный бэкенд кеширования (ролл-аут с февраля 2025), обеспечивающий повышенную производительность и надёжность.

## Основные концепции

### Как работает кеширование

Процесс состоит из двух этапов:

1. **Восстановление (Restore)**: В начале задачи (`job`) `action` `actions/cache` пытается найти кеш по указанному ключу (`key`). Если найдено точное совпадение, содержимое кеша восстанавливается в указанную директорию (`path`). Если точного совпадения нет, происходит поиск по префиксу с помощью `restore-keys`.
2. **Сохранение (Save)**: В конце задачи, если не было найдено точного совпадения ключа на этапе восстановления, `action` создает новый кеш и загружает в него содержимое из указанной директории.

**Cache Service v2** (с февраля 2025):

- Улучшенная производительность и надёжность
- Требует `actions/cache@v4` или выше
- Для self-hosted runners необходима версия ≥2.231.0
- Гранулярный контроль через отдельные действия `actions/cache/restore` и `actions/cache/save`

### Ключи кеша

Правильный подбор ключа — залог эффективности кеширования.

- **`key`** (обязательный): Уникальный идентификатор для кеша. Сборка будет использовать кеш только при **полном совпадении** этого ключа.
- **`restore-keys`** (опциональный): Список префиксов или полных ключей для "частичного" восстановления. Если `key` не найден, будет использован последний кеш, соответствующий одному из `restore-keys`. Это полезно, когда обновилась одна зависимость, а не все.

Ключ обычно состоит из нескольких частей:

- Тип ОС (`runner.os`).
- Имя менеджера пакетов (e.g., `npm`, `pip`).
- **Хеш файла зависимостей**: `hashFiles('**/package-lock.json')` или `hashFiles('**/requirements.txt')`. Это самая важная часть: как только файл зависимостей меняется, меняется и хеш, что приводит к созданию нового кеша.

### Ограничения

- **Размер**: Максимальный размер одного кеша — 10 ГБ. Общий размер всех кешей на репозиторий — 10 ГБ по умолчанию (может быть увеличен до 10 ТБ для организаций/enterprise).
- **Время жизни**: Кеш, который не использовался более 7 дней, автоматически удаляется.
- **Неизменяемость (Immutability)**: Кеш с определённым ключом нельзя изменить. Можно только создать новый кеш с новым ключом.
- **Политика вытеснения**: При превышении лимита удаляются наименее используемые кэши (LRU).
- **Rate Limits**:
  - Загрузка: 200 запросов в минуту на репозиторий
  - Скачивание: 1500 запросов в минуту на репозиторий
- **Тарификация**: Использование сверх 10 ГБ тарифицируется (например, 50 ГБ ≈ $2.80/мес). Возможна установка бюджетов для блокировки записи при превышении.
- **Безопасность**: Не хранить чувствительные данные (токены, пароли) в кэше. Кеш доступен для чтения всем, кто имеет доступ к репозиторию (включая форки для base branch).

### Дополнительные возможности (2025–2026)

- **Кросс-ОС кеширование**: Опция `enableCrossOsArchive` для обмена кешем между платформами (opt-in).
- **Управление потоком**:
  - `fail-on-cache-miss`: Ошибка при отсутствии кеша
  - `lookup-only`: Только проверка наличия без скачивания
- **Таймауты**: Переменная `SEGMENT_DOWNLOAD_TIMEOUT_MINS` (по умолчанию 10 мин) для предотвращения зависаний.
- **Пути в Windows**: Использовать `~` вместо переменных окружения (например, `~\AppData\Local` вместо `%LocalAppData%`).

## Практические сценарии

### Сценарий 1: Кеширование NPM зависимостей

Классический пример для Node.js проектов. `package-lock.json` гарантирует, что кеш будет обновлен только при изменении зависимостей.

**Встроенная поддержка в `setup-node`** (рекомендуется):

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm' # Встроенное кеширование
          cache-dependency-path: '**/package-lock.json'

      - name: Install dependencies
        run: npm ci

      - name: Run tests
        run: npm test
```

**Ручное управление через `actions/cache@v5`** (для гранулярного контроля):

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Cache Node.js modules
        id: cache-npm
        uses: actions/cache@v5
        with:
          path: ~/.npm
          key: ${{ runner.os }}-npm-${{ hashFiles('**/package-lock.json') }}
          restore-keys: |
            ${{ runner.os }}-npm-

      - name: Install dependencies
        if: steps.cache-npm.outputs.cache-hit != 'true'
        run: npm ci

      - name: Run tests
        run: npm test
```

### Сценарий 2: Кеширование для Python с pip

Аналогичный пример для Python. `restore-keys` позволяет использовать старый кеш, если, например, была добавлена новая зависимость, что ускоряет установку.

**Встроенная поддержка в `setup-python`** (рекомендуется):

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: '**/requirements.txt'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        run: pytest
```

### Встроенная поддержка в setup-actions

Многие `setup-*` actions имеют встроенную поддержку кеширования — это предпочтительный способ:

| Менеджер пакетов | Setup action | Значение `cache` |
| :--- | :--- | :--- |
| npm, Yarn, pnpm | `actions/setup-node@v4` | `cache: 'npm'`, `cache: 'yarn'`, `cache: 'pnpm'` |
| pip, pipenv, Poetry | `actions/setup-python@v5` | `cache: 'pip'`, `cache: 'pipenv'`, `cache: 'poetry'` |
| Gradle, Maven | `actions/setup-java@v4` | `cache: 'gradle'`, `cache: 'maven'` |
| RubyGems | `actions/setup-ruby@v1` | `cache: 'bundler'` |
| Go (go.sum) | `actions/setup-go@v5` | `cache: true` |
| .NET NuGet | `actions/setup-dotnet@v4` | `cache: true` |

## Дополнительная информация

Другие техники оптимизации CI/CD описаны в **[Оптимизация воркфлоу](./Optimization.md)**. Готовые действия доступны в **[Marketplace Actions](./Marketplace_Actions.md)**. Официальная документация: [Caching dependencies to speed up workflows](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows).
