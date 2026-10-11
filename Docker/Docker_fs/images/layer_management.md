# Docker: Анализ и управление слоями образа

**Актуально для:** Docker 24.x–27.x, Kubernetes 1.29.x–1.32.x, CI/CD-раннеры на основе Linux

## Определения

- **Слой образа (Image Layer)** — неизменяемый (read-only) слепок файловой системы, создаваемый инструкциями `RUN`, `COPY` или `ADD`. Образ представляет собой стек таких слоев.
- **Драйвер хранения (Storage Driver)** — механизм ядра (например, **[OverlayFS](../docker_overlayfs.md)**), управляющий объединением слоев в единое представление и обеспечивающий работу контейнера.
- **Copy-on-Write (CoW)** — стратегия оптимизации, при которой файл копируется из нижних (read-only) слоев в верхний (writable) только в момент попытки его изменения.
- **Анализ слоев (Layer Analysis)** — инспекция содержимого и размера каждого шага сборки для поиска неэффективных операций (временных файлов, дубликатов, небезопасных пакетов).
- **Механизм Whiteout** — специальный маркер в файловой системе (используемый в OverlayFS), который скрывает файл в "объединенном" представлении, если он был удален в более высоком слое, хотя физически он остается в нижних слоях.
- **Squash (сжатие слоев)** — объединение всех слоев, созданных инструкциями `Dockerfile`, в один итоговый слой поверх базового образа. Позволяет убрать "мусор" и случайно попавшие секреты, но полностью уничтожает преимущества кэширования слоев.
- **Висячий слой (Dangling layer)** — слой, на который не ссылается ни один тег образа и который не используется ни одним запущенным контейнером. Возникает после пересборки образа с тем же тегом (старые слои "осиротевают") или после squashing. Занимает место на диске, пока не будет очищен.
- **Кэш сборки (Build cache)** — локальное хранилище промежуточных слоев, переиспользуемых при повторных сборках. Сбрасывается вручную через `docker buildx prune` (для BuildKit) или `docker builder prune`.

## Предварительные требования

Перед выполнением сценариев убедитесь, что окружение соответствует следующим условиям:

- **Docker Engine 24.0+** (BuildKit включён по умолчанию начиная с 23.0; для явного включения в старых версиях — переменная `DOCKER_BUILDKIT=1`). Проверка:
  ```bash
  docker --version
  # → Docker version 27.3.1, build ce12230
  ```
- **BuildKit / Buildx** для продвинутых сценариев (`buildx imagetools`, кэш-экспортеры):
  ```bash
  docker buildx version
  # → github.com/docker/buildx v0.18.0 ...
  ```
- **dive** (версия 0.11+ или 0.12+) — для интерактивного и CI-анализа слоев. Установка (Linux/macOS):
  ```bash
  dive --version
  # → dive 0.12.0
  ```
- **Docker Scout** — встроен в Docker Desktop, либо как CLI-плагин `docker scout`. Проверка:
  ```bash
  docker scout version
  # → Docker Scout version 1.10.0
  ```
- **Локально собранный образ** для анализа (история слоев доступна только для образов, собранных или загруженных локально):
  ```bash
  docker images my-app
  # → REPOSITORY   TAG       IMAGE ID       CREATED         SIZE
  # → my-app       latest    a1b2c3d4e5f6   5 minutes ago   312MB
  ```
- **Доступ к Docker daemon** (`/var/run/docker.sock` или `DOCKER_HOST`) — требуется для `docker history`, `docker save`, `docker system df`.

## Основные концепции

### Анатомия слоев в OverlayFS

Docker использует драйвер `overlay2` для эффективного наслоения данных. Структура включает:
- **LowerDir:** Неизменяемые слои образа (базовая ОС, библиотеки).
- **UpperDir:** Записываемый слой контейнера или текущий слой сборки.
- **MergedDir:** Объединенное представление, которое видит процесс внутри контейнера.

Подробный разбор работы драйвера (copy-up, whiteout, opaque-директории, `d_type`, лимит 128 слоев): **[Драйвер хранения OverlayFS](../docker_overlayfs.md)**.

> **Где физически живут слои (version note).** В классическом режиме демона слои хранятся в `/var/lib/docker/overlay2/`. Начиная с Docker 29.0 при включённом `containerd-snapshotter` слои перемещаются в `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/` и могут занимать диск дважды (сжатый content store + распакованный snapshotter). Подробнее — в файле по OverlayFS.

### Персистентность и проблема удаления

В Docker удаление файла в новом слое **не освобождает** место, занятое им в предыдущих.
1. `RUN apt-get install` → Создает слой с пакетами (+100MB).
2. `RUN apt-get purge` → Создает новый слой с **whiteout-файлами** (+1KB), которые лишь помечают старые файлы как "удаленные".
3. **Результат:** Итоговый образ по-прежнему весит 100MB+.

**Золотое правило:** Объединяйте установку и очистку в одной инструкции `RUN` (цепочки `&&`), чтобы изменения происходили внутри одного слоя. Подробнее: **[Оптимизация сборки Docker-образов](../../Dockerfile/Docker_best_practices/build_optimization.md)**.

### Особенности BuildKit

Современный движок **BuildKit** управляет слоями иначе:
- **Параллелизм:** Сборка независимых этапов (stages) происходит одновременно.
- **Ленивое вычисление:** Если результат инструкции не используется в финальном образе (например, промежуточный этап multi-stage), слои для него могут вообще не создаваться в реестре.

### Жизненный цикл слоя

Каждый слой проходит путь: **инструкция Dockerfile → временный `upperdir` (overlay mount) → commit как read-only слой → сохранение в кэше сборки → push/pull в реестр → переиспользование при следующей сборке**. Инвалидация кэша происходит каскадно: изменение слоя N сбрасывает кэш всех последующих слоев N+1, N+2… Детально про порядок инструкций и инвалидацию — в **[Оптимизации сборки](../../Dockerfile/Docker_best_practices/build_optimization.md)**.

### Управление слоями с точки зрения SRE/DevOps

С точки зрения эксплуатации слои образа — это не только размер артефакта, но и:
- **Потребление диска на хосте:** каждый запущенный контейнер создаёт writable layer поверх read-only слоёв образа. На хостах с большим количеством контейнеров ( оркестраторы, CI-раннеры) это может приводить к заполнению диска.
- **Сетевой трафик при деплое:** при `docker pull` тянутся только недостающие слои; повторное деплой того же образа не передаёт данные по сети. Это основа кэширования на registry edge и CI-runner'ах.
- **Кэш BuildKit на раннере:** локальный кэш ускоряет повторные сборки, но при переполнении диска требует ручного или автоматического prune. На эфемерных раннерах кэш уничтожается вместе с виртуальной машиной; на self-hosted пулах — накапливается.
- **containerd snapshotter (Docker 29.0+):** при включённом `containerd-snapshotter` слои хранятся дважды — в content store (сжатые) и в snapshotter (распакованные). Это увеличивает потребление диска примерно в 1.5–2 раза по сравнению с классическим overlay2.
- **Дeduplication на хосте:** Docker автоматически дедуплицирует слои между образами (один и тот же слой `sha256:...` хранится единожды). `docker system df` показывает экономию; при удалении последнего образа, использующего слой, он становится dangling и занимает место до prune.

Для мониторинга потребления диска слоями используйте:
```bash
docker system df
# → TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# → Images          12        5         4.1GB     2.3GB (56%)
# → Containers      8         8         1.2GB     0B
# → Local Volumes   5         3         3.4GB     1.1GB (32%)
# → Build Cache     34        0         1.8GB     1.8GB

docker system df -v
# → детализация по образам и слоям с дайджестами
```

## Практические сценарии

### Сценарий 1: Базовая инспекция через `docker history`

Позволяет увидеть размер каждого слоя и команду, которая его создала.

```bash
docker history --human --format "{{.ID}}: {{.CreatedBy}} {{.Size}}" my-app:latest
```

Ожидаемый вывод (пример):

```text
# → a1b2c3d4e5f6: CMD ["python" "app.py"]                       0B
# → 9b7c4d20f1a2: RUN pip install -r requirements.txt          45.2MB
# → <missing>:     COPY requirements.txt /app/                  1.3kB
# → <missing>:     WORKDIR /app                                 0B
# → 7c8d9e0f1a2b: /bin/sh -c #(nop)  ENV PYTHONUNBUFFERED=1     0B
```

- **`<missing>`**: Указывает на слои, созданные в BuildKit или загруженные из реестра (локально доступны только метаданные).
- **Размер 0B**: Обычно инструкции `ENV`, `LABEL`, `EXPOSE` или `WORKDIR`, которые меняют только конфиг JSON, а не ФС.

**Валидация:** команда возвращает таблицу, где сумма размеров слоев приблизительно равна `docker images my-app` (с учетом сжатия при хранении). Отсутствие вывода или ошибка `Error: no such image` означает, что образ не собран локально.

### Сценарий 2: Глубокий анализ с помощью `dive`

Инструмент для интерактивного исследования изменений ФС между слоями.

```bash
dive my-app:latest
```

**На что смотреть:**
- **Efficiency Score:** % полезных данных. Низкий балл означает, что много файлов было изменено или удалено в последующих слоях.
- **Wasted Space:** Показывает файлы, которые дублируются или занимают место впустую из-за CoW.

**Режим CI (для пайплайнов)** — неинтерактивная проверка с порогом эффективности:

```bash
CI=true dive my-app:latest --lowestEfficiency 0.90
# → Using CI mode (non-interactive)
# → Image efficiency: 0.93 (target 0.90) - PASS
# → exit code 0
```

**Валидация:** при эффективности ниже порога `dive` возвращает ненулевой exit code (например, `1`) — удобно для блокировки сборки в CI. Подробнее о настройке порогов и других линтерах — в **[Инструментах оптимизации Dockerfile](../../Dockerfile/dockerfile_optimization_tools.md)**.

### Сценарий 3: Аудит слоев через `docker scout`

Современный инструмент Docker для анализа безопасности и оптимизации слоев.

```bash
# Поиск конкретных слоев, вносящих уязвимости
docker scout cves --locations my-app:latest

# Получение рекомендаций по смене базового образа
docker scout recommendations my-app:latest
```

Ожидаемый вывод (пример):

```text
# → ✔ No vulnerabilities found (в случае чистого образа)
# → либо список CVE с указанием слоя/пакета:
# →   HIGH CVE-2024-... in libssl3 (introduced in layer RUN apt-get install ...)
```

`docker scout` может предложить заменить тяжелый базовый образ на более легкую и безопасную альтернативу (например, `alpine` или `distroless`), что радикально уменьшит количество слоев и общий размер.

**Валидация:** успешный анализ завершается без ошибок аутентификации в Docker Scout; при первом запуске может потребоваться `docker scout login` или `docker login`.

### Сценарий 4: Сжатие слоев (Squashing)

Объединяет все слои, созданные в текущем Dockerfile, в один финальный слой поверх базового.

```bash
# Классический сборщик (Docker Engine, legacy builder)
docker build --squash -t my-app:prod .

# BuildKit / Buildx (флаг --squash поддерживается в новых версиях, но считается
# антипаттерном — предпочтительнее уменьшать число слоев в самом Dockerfile)
docker buildx build --squash -t my-app:prod .
```

| За | Против |
| :--- | :--- |
| Минимальный размер артефакта. | Полная потеря преимуществ кэширования слоев при push/pull. |
| Удаление случайно добавленных секретов. | Высокая нагрузка на сеть при обновлении минорных версий. |

**Валидация:** после squashing количество слоев резко сокращается (базовый + 1):

```bash
docker history my-app:prod --format '{{.ID}} {{.Size}}'
# → <base>    BASE IMAGE (например, 40MB)
# → <squashed>  остальные слои слиты в один (например, 25MB)
```

> **Замечание по версиям.** `--squash` в классическом `docker build` стабилен давно; в Buildx он появился позже и часто отключает кэш. В продакшене приоритет — multi-stage + `COPY --link`, а не squashing (см. **[Оптимизацию сборки](../../Dockerfile/Docker_best_practices/build_optimization.md)**).

### Сценарий 5: Инспекция слоев образа из реестра без скачивания

Позволяет увидеть размер и дайджест каждого слоя удалённого образа, не выполняя `docker pull` (экономия трафика и диска).

```bash
# Список слоев с размерами и дайджестами через Buildx
docker buildx imagetools inspect my-app:latest --format '{{json .Manifest}}'
# → {"schemaVersion":2,"mediaType":"...","config":{...},
# →  "layers":[{"mediaType":"application/vnd.docker.image.rootfs.diff.tar.gzip",
# →             "size":47234567,"digest":"sha256:9b7c4d20f1a2..."},
# →            {"mediaType":"...","size":1337856,"digest":"sha256:1c2d3e4f5a6b..."}]}
```

Альтернативы без daemon-зависимости — `crane manifest` или `skopeo inspect --raw`:

```bash
skopeo inspect --raw docker://registry.example.com/my-app:latest | jq '.layers[] | {size,digest}'
# → {"size":47234567,"digest":"sha256:9b7c4d20f1a2..."}
```

**Валидация:** JSON содержит массив `layers`, где сумма `size` совпадает с размером образа в реестре. Ошибка `manifest unknown` означает неверный тег/реестр.

### Сценарий 6: Извлечение и анализ конкретного слоя

Когда нужно точно понять, какие файлы появились в конкретном слое (например, для поиска секрета или временного файла).

```bash
# 1. Сохраняем образ в tar-архив
docker save my-app:latest -o my-app.tar

# 2. Смотрим структуру архива (каждый слой — отдельная папка с layer.tar)
tar -tf my-app.tar
# → 9b7c4d20f1a2.../layer.tar
# → 1c2d3e4f5a6b.../layer.tar
# → manifest.json

# 3. Распаковываем только нужный слой в отдельную папку
mkdir -p /tmp/layer-inspect
tar -xf my-app.tar 9b7c4d20f1a2.../layer.tar -C /tmp/layer-inspect

# 4. Анализируем содержимое
find /tmp/layer-inspect -type f | head
# → /tmp/layer-inspect/etc/ssl/certs/ca-certificates.crt
# → /tmp/layer-inspect/usr/bin/python3
```

**Валидация:** в `/tmp/layer-inspect` оказывается плоская ФС, соответствующая изменениям этого слоя. Пустой результат `find` означает, что слой содержит только метаданные (0B-слой).

> Без `docker save` то же достигается через `skopeo copy docker://... dir:/tmp/img` — слои сохраняются как отдельные файлы в каталоге.

### Сценарий 7: Автоматическая минимизация через docker-slim

Инструмент, который запускает образ, профилирует реально используемые файлы и собирает "худой" образ, отбрасывая всё неиспользуемое (включая целые слои).

```bash
docker-slim build --target my-app:latest --tag my-app:slim
# → optimising image my-app:latest
# → image size: 312MB -> 18MB (≈ 17x smaller)
# → new image: my-app:slim
```

**Валидация:** проверьте работоспособность уменьшенного образа перед деплоем:

```bash
docker run --rm my-app:slim python -c "import app; print('ok')"
# → ok
```

**Ограничение:** docker-slim не знает о файлах, загружаемых динамически в рантайме, поэтому требует прогона реальных сценариев использования (`--http-probe` / кастомные команды). Подробнее — в **[Инструментах оптимизации Dockerfile](../../Dockerfile/dockerfile_optimization_tools.md)**.

### Сценарий 8: Экспорт/импорт кэша BuildKit для CI

На самоcтоятельных (self-hosted) раннерах с ограниченным диском или высоким trafiкcом можно экспортировать кэш BuildKit в registry и переиспользовать его между пайплайнами, не сохраняя локально:

```bash
# Экспорт кэша в registry (в конце пайплайна)
docker buildx build \
  --cache-to type=registry,ref=my-registry.com/build-cache/my-app:main \
  --cache-from type=registry,ref=my-registry.com/build-cache/my-app:main \
  -t my-registry.com/my-app:$CI_COMMIT_SHA \
  --push .

# Импорт кэша при следующей сборке (в начале пайплайна)
docker buildx build \
  --cache-from type=registry,ref=my-registry.com/build-cache/my-app:main \
  -t my-registry.com/my-app:$CI_COMMIT_SHA \
  --push .
```

**Валидация:** при успешном импорте в логах сборки появляется `=> CACHED` для тех шагов, которые не изменились. Кэш в registry занимает место аналогично образам; настройте retention policy для тегов `build-cache/*`.

**SRE-нюансы:**
- Используйте отдельный репозиторий или namespace для кэша, чтобы не смешивать с продакшен-образами.
- Для air-gapped окружений кэш нельзя экспортировать в внешний registry; используйте `type=local` с shared volume или Nexus/Artifactory как локальный registry.
- `--cache-to=type=inline` помещает кэш прямо в манифест образа (подходит для маленьких проектов, увеличивает размер образа).

## Дополнительная информация

### Сравнение методов управления размером

| Метод | Сложность | Влияние на кэш | Эффективность |
| :--- | :--- | :--- | :--- |
| **RUN && (цепочки)** | Низкая | Сохраняется | Средняя |
| **Multi-stage builds** | Средняя | Сохраняется | **Максимальная** |
| **Squashing (--squash)** | Низкая | Уничтожается | Высокая |
| **docker-slim** | Средняя | Не применимо (новый образ) | Максимальная* |

\* docker-slim даёт максимальное сжатие, но требует рантайм-профилирования и усложняет воспроизводимость сборки.

**Multi-stage builds** остается приоритетным методом, так как позволяет отсекать "мусор" (компиляторы, исходники) на этапе сборки, сохраняя кэшируемость промежуточных слоев.

### OCI 1.1 и Referrers API

В современных реестрах (Harbor, Docker Hub) аттестации (SBOM, подписи) могут прикрепляться к образу не как дополнительные слои, а как связанные артефакты. Это позволяет анализировать состав слоев, не скачивая сам образ (см. Сценарий 5).

### Troubleshooting

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Образ большой, хотя файлы «удалили» | Удаление в отдельном `RUN` создаёт whiteout, файл физически остаётся в нижнем слое | `dive` показывает высокий Wasted Space | Объединить установку и очистку в одну цепочку `&&`; использовать multi-stage |
| `dive` показывает Efficiency < 0.9 | Мусор/временные файлы в слоях | `CI=true dive ... --lowestEfficiency 0.90` | Почистить Dockerfile, удалить кэши пакетных менеджеров в том же `RUN` |
| `docker history` показывает `<missing>` | BuildKit/registry — метаданные недоступны локально | норма для современных сборок | Не является ошибкой; полные данные видны после локальной сборки |
| `docker build --squash` не ускоряет pull | Squash уничтожает кэш слоев | `docker history` показывает 1 слой | Уменьшать число слоев в Dockerfile (multi-stage, `COPY --link`) |
| Место на диске растёт после пересборок | Осиротевшие (dangling) слои | `docker images -f dangling=true`, `docker system df` | `docker system prune -f` (см. Best Practices) |
| `mount` / `too many layers` при сборке | Превышен лимит 128 нижних слоев overlay2 | `docker history my-app \| wc -l` | Укрупнить `RUN`, применить multi-stage |
| Секрет попал в образ, хотя удалён в следующем `RUN` | Whiteout только скрывает файл | `docker save` + распаковка слоя (Сценарий 6) | Использовать `--mount=type=secret` (BuildKit), а не `COPY` секрета |
| Диск self-hosted раннера заполнен кэшем BuildKit | `buildx prune` не настроен / кэш накапливается между задачами | `docker system df` — Build Cache > 10GB | Добавить prune в post-job шаг: `docker buildx prune -f -a --filter "until=24h"` |
| `docker system df` показывает высокий Reclaimable, но `prune` не освобождает место | Образы используются running containers или имеют теги | `docker ps -a`, `docker images` | Удалить неиспользуемые контейнеры (`docker container prune`) или пересобрать с `--squash` для немедленного эффекта |
| containerd snapshotter: диск занят вдвое больше ожидаемого | Docker 29.0+ с `containerd-snapshotter` хранит слои в content store + snapshotter | `df -h /var/lib/containerd`, `du -sh /var/lib/docker` | Оценить компрессию content store; дляProduction рассмотреть классический overlay2 или настроить retention |
| `docker scout` не запускается в CI | Отсутствует `docker scout login` или плагин не установлен в раннере | `docker scout version` → error | Установить плагин: `docker plugin install docker/scout` или использовать standalone binary |
| Кэш BuildKit не импортируется в air-gapped окружение | `--cache-from type=registry` требует доступа к registry | `docker buildx build` → `cache import: failed` | Использовать `type=local` с shared volume или Nexus registry внутри периметра |
| `docker buildx imagetools inspect` не показывает слои | Образ pushed в OCI-формате без legacy Docker media types | `docker buildx build --output type=image` с `--provenance` | Использовать `--format type=docker` при push или `skopeo inspect --raw` |

### Best Practices & Cleanup

- **Золотое правило:** цепочки `RUN &&` + multi-stage — приоритетный способ уменьшения слоев; они сохраняют кэшируемость, в отличие от squashing.
- **Используйте `COPY --link`** (BuildKit) для независимых слоев — ускоряет переиспользование и уменьшает каскадную инвалидацию кэша.
- **Регулярная оценка места:**
  ```bash
  docker system df
  # → TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
  # → Images          12        5         4.1GB     2.3GB (56%)
  # → Build Cache     34        0         1.8GB     1.8GB
  ```
- **Автоматическая очистка на CI-раннерах:** добавьте в post-job шаг пайплайна:
  ```bash
  docker buildx prune -f -a --filter "until=24h"
  docker builder prune -f --filter "until=24h"
  docker system prune -f --filter "until=24h"
  ```
  На GitHub-hosted/GitLab shared раннерах это не обязательно — ВМ удаляется. На self-hosted пулах prune обязателен.
- **Очистка висячих слоев и кэша:**
  ```bash
  docker system prune -f            # удаляет dangling images, containers, networks
  docker buildx prune -f            # очищает build cache BuildKit
  docker builder prune -f           # альтернатива для legacy builder
  ```
- **Retention policy для BuildKit cache:** если используете `--cache-to type=registry`, настройте retention на уровне registry (Harbor: `artifactRetention`, GHCR: package settings) — кэш без retention растёт бесконечно.
- **SRE-мониторинг:** добавьте в метрики/дашборды:
  - `docker system df` — процент reclaimable
  - `docker info` — `BuildKit`, `Storage Driver`, количество образов/контейнеров
  - Дисковое пространство `/var/lib/docker` и `/var/lib/containerd` (для Docker 29+)
  - Для оркестраторов: `kubectl top node` + `df -h` на каждом узле
- **Откат и безопасность:** операции squashing и docker-slim **необратимы** локально — всегда сохраняйте исходный `Dockerfile` и тег до модификации (например, `my-app:pre-slim`). Восстановить слой после `docker system prune` можно только из реестра (`docker pull`).
- **Осторожно с `docker image prune -a`:** удаляет все неиспользуемые образа, что может сломать локальные контейнеры; применяйте только на CI-runner'ах или после подтверждения.
- **containerd snapshotter:** при переходе на Docker 29+ с `containerd-snapshotter` учитывайте двойное хранение слоёв; для систем с ограниченным диском оцените компрессию content store (`/var/lib/containerd`) и настройте `--containerd-snapshotter` параметры.
- **ImagePullPolicy в Kubernetes:** `imagePullPolicy: Always` отключает использование локального кэша на узле и заставляет kubelet тянуть все слои при каждом деплое; для production используйте `IfNotPresent` с дайджестами.
- **Эфемерные vs self-hosted раннеры:** на эфемерных раннерах prune не требуется — ВМ удаляется; на self-hosted добавляйте prune в pipeline и мониторьте `/var/lib/docker` через node-exporter.

### Edge Cases

- **`<missing>` в `docker history`** — не ошибка. Означает, что слой собран в BuildKit или пришёл из реестра; локально доступны только метаданные промежуточного шага.
- **0B-слои (ENV/LABEL/EXPOSE/WORKDIR/CMD/ENTRYPOINT)** не создают данных в ФС, но меняют `config.json` образа, поэтому изменяют его дайджест.
- **Whiteout сохраняет файл физически.** Удалённый в следующем `RUN` секрет остаётся в нижнем слое и виден через `docker save` (см. Сценарий 6 / Troubleshooting). Для секретов используйте `RUN --mount=type=secret`.
- **Opaque whiteout** — удаление всей директории создаёт в `upperdir` пустую директорию с атрибутом `trusted.overlay.opaque=y`, полностью скрывающим содержимое нижних слоев.
- **Лимит 128 слоёв** в `overlay2` (ограничение длины аргументов `mount`) — при превышении сборка падает.
- **Squash уничтожает кэш слоёв** → каждое обновление требует полной перекачки слоя; для частых патчей это контрпродуктивно.
- **containerd snapshotter (Docker 29.0+):** слои могут храниться дважды (content store + распакованный snapshotter), что увеличивает потребление диска на хосте.
- **Multi-stage ленивость:** BuildKit может вообще не создавать слои промежуточных стадий, если они не используются в финальном образе — `docker history` финального образа их не покажет.
- **`dive` и реестр:** `dive` анализирует только локально доступные образы (через daemon); для анализа удалённого образа сначала нужен `docker pull` либо используйте Сценарий 5.
- **BuildKit cache import/export и air-gap:** в изолированных сетях `type=registry` недоступен; используйте `type=local` с общим volume или внутренний registry (Nexus, Harbor). Retention policy для тегов кэша должна быть отдельной от образов.
- **CoW overhead на write-heavy workloads:** базы данных, очереди, логи на overlay2 могут давать латентность до 2x при первом copy-up. Для production используйте named volumes или `tmpfs` для write-intensive директорий.
- **Page Cache thrashing при нехватке RAM:** при переполнении памяти ядро вытесняет страницы кэша overlay2; повторный доступ к базовым слоям идёт с диска. Для SRE: мониторинг `pgpgout`/`pgins` через `sar -B` или `vmstat`.
- **Layer deduplication и hardlink:** Docker пытается хардлинкать идентичные файлы между слоями; на файловых системах без `ftype=1` (XFS) или `reflink=1` это может не работать, что снижает эффективность хранения.
- **`docker system df` vs `du -sh /var/lib/docker`:** `docker system df` считает только используемые объекты; `du` показывает физическое место на диске. Разница = dangling/unreferenced слои, готовые к prune.

### См. также

- **[Основы Docker-образов](./docker_images_basics.md)** — анатомия и жизненный цикл.
- **[Оптимизация сборки Docker-образов](../../Dockerfile/Docker_best_practices/build_optimization.md)** — детальное руководство по multi-stage.
- **[Драйвер хранения OverlayFS](../docker_overlayfs.md)** — низкоуровневая работа со слоями.
