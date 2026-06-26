# Docker: Перенос и экспорт образов (save, load, export, import)

Команды сериализации данных в архивы формата `tar (Tape Archive)` служат для перемещения образов и файловых систем в изолированные среды или для миграции данных.

## Определения

Docker предоставляет два набора команд для работы с архивами, которые имеют принципиальные различия в объектах обработки и сохраняемых данных.

- **`docker save` / `docker load`**: Инструменты для работы с **образами (images)**.
  - **`docker save`**: Сохраняет один или несколько образов в архив, полностью сохраняя структуру слоёв, теги, историю и метаданные.
  - **`docker load`**: Восстанавливает образы из архива, созданного через `docker save`, в локальное хранилище Docker.

- **`docker export` / `docker import`**: Инструменты для работы с **файловой системой контейнера (container's filesystem)**.
  - **`docker export`**: Создаёт "плоский" (flattened) архив файловой системы конкретного контейнера. Вся информация о слоях и истории сборки при этом теряется.
  - **`docker import`**: Создаёт **новый, однослойный** образ на основе архива файловой системы.

## Основные концепции

### Сравнение механизмов переноса

| Критерий | `save` / `load` | `export` / `import` |
| :--- | :--- | :--- |
| **Объект обработки** | **Образ (Image)** | **Контейнер (Container)** |
| **Слои (Layers)** | ✅ Сохраняются | ❌ Объединяются в один слой |
| **Метаданные (ENV, CMD)** | ✅ Сохраняются | ❌ Теряются |
| **Назначение** | Перенос образов в закрытые контуры (air-gapped), бэкап образов | Миграция файловых систем, создание базовых образов из контейнеров |

### Выбор инструмента

- **Используйте `docker save` и `docker load` для:**
  - Переноса протестированных образов на серверы без доступа к сети или реестрам.
  - Создания точных резервных копий образов со всей историей.
  - Передачи образа для отладки с сохранением всех промежуточных слоёв.

- **Используйте `docker export` и `docker import` для:**
  - Экспорта текущего состояния файловой системы контейнера для анализа или использования в других системах виртуализации.
  - Создания минималистичного базового образа на основе настроенного вручную контейнера (в исключительных случаях, когда `Dockerfile` недоступен).

## Практические сценарии

### Сценарий 1: Перенос образа в изолированную среду (`save`/`load`)

1. **На машине с доступом к сети**: Сохраняем образ в архив.

    ```bash
    docker pull nginx:latest
    docker save -o nginx-image.tar nginx:latest
    # → Файл nginx-image.tar успешно создан
    ```

2. **Перенос файла**: Используйте `scp (Secure Copy Protocol)` или `USB (Universal Serial Bus)` накопитель для перемещения файла на целевой сервер.

3. **На целевом сервере**: Загружаем образ.

    ```bash
    docker load -i nginx-image.tar
    # → Loaded image: nginx:latest

    docker images | grep nginx
    # → nginx    latest    605c77e624dd    2 weeks ago    141MB
    ```

### Сценарий 2: Загрузка образа в кластер Kubernetes без registry (air-gapped)

В Kubernetes на worker-нодах Docker обычно не используется — контейнеры запускаются через CRI-совместимые runtime (`containerd`, `CRI-O`). Если registry недоступен, образ можно загрузить напрямую.

```bash
# 1. Сохранить образ на машине с доступом к registry
docker save -o my-app.tar my-app:latest

# 2. Передать архив на worker-ноду (через scp)
scp my-app.tar user@worker-node:~/

# 3. Загрузить в runtime в зависимости от CRI:

# Для CRI-O — используем podman
podman load -i my-app.tar

# Для containerd — используем ctr (часто требует sudo)
sudo ctr -n k8s.io images import my-app.tar

# Для Docker runtime — стандартный docker load
docker load -i my-app.tar
```

После загрузки образ будет доступен kubelet'у и поды смогут стартовать без обращений к registry.

**Проверка загруженных образов:**

```bash
# CRI-O
podman images | grep my-app

# containerd
sudo ctr -n k8s.io images list | grep my-app

# Docker
docker images | grep my-app
```

### Сценарий 3: Создание образа из файловой системы контейнера (`export`/`import`)

1. **Создание и модификация контейнера**:

    ```bash
    docker run --name temp-container ubuntu:22.04 touch /my-new-file
    # → Контейнер запущен и файл создан
    ```

2. **Экспорт файловой системы**:

    ```bash
    docker export temp-container > container-fs.tar
    # → Архив container-fs.tar сформирован
    ```

3. **Импорт как нового образа**:

    ```bash
    cat container-fs.tar | docker import - my-flat-image:1.0
    # → sha256:f9e4b5b8129c... (создан новый образ)
    ```

4. **Проверка структуры**: Новый образ будет состоять из одного слоя.

    ```bash
    docker history my-flat-image:1.0
    # → IMAGE          CREATED         CREATED BY          SIZE      COMMENT
    # → f9e4b5b8129c   1 minute ago                        4.09kB    Imported from -
    ```

## Дополнительная информация

- **Приоритет реестров**: Для большинства задач (разработка, Continuous Integration/Continuous Deployment — непрерывная интеграция и доставка) следует использовать **[Docker Registry](../../docker_registries.md)**.
- **Сжатие данных**: Для экономии места при передаче архивы можно сжимать.
  - Сохранение: `docker save my-image | gzip > image.tar.gz`
  - Загрузка: `gunzip -c image.tar.gz | docker load`

### Смотрите также

- [Основы Docker-образов](./docker_images_basics.md)
- [Создание образов через Docker Commit](../docker_commit.md)
- [Реестры Docker](../../docker_registries.md)
