# GPU и ML-нагрузки в Dockerfile

**Актуально для:** Docker Engine 29.x / NVIDIA Container Toolkit 1.20.1 / CDI 1.1.1 / CUDA 13.4 (LTS-ветка 12.9).

## Определения

**GPU-ускоренный контейнер** — контейнер, которому проброшено устройство GPU хоста для вычислений (CUDA, inference, training, рендеринг). Доступ реализуется через NVIDIA Container Toolkit, а современный стандарт — через CDI.

**CUDA (Compute Unified Device Architecture)** — параллельная вычислительная платформа NVIDIA. В контейнере CUDA — это userspace-библиотеки и компилятор `nvcc`; сам драйвер GPU остаётся на хосте.

**NVIDIA Container Toolkit** — набор компонентов для доступа контейнеров к GPU: `nvidia-container-runtime`, `nvidia-ctk` (CLI), `nvidia-cdi-hook`, `nvidia-container-runtime-hook`, `libnvidia-container1`. Установка на хост — в [Установка Docker Engine: NVIDIA Container Toolkit](../../Docker/docker_install_ubuntu.md).

**CDI (Container Device Interface)** — открытая спецификация (с v1.12.0 NVIDIA Container Toolkit), абстрагирующая доступ к устройству (GPU) для любого CDI-aware runtime (Docker, Podman, containerd, CRI-O). Заменяет устаревший флаг `--gpus` и привязку к `nvidia-container-runtime`. Текущая версия спецификации CDI — 1.1.1 (CNCF, Sep 2026).

**MIG (Multi-Instance GPU)** — разделение физического GPU на изолированные инстансы (Ampere+). В CDI — устройства `nvidia.com/gpu=mig{GPU_INDEX}:{MIG_INDEX}`.

**`NVIDIA_VISIBLE_DEVICES`** — переменная, определяющая, какие GPU видны в контейнере (`all`, UUID, индекс). Значение `void` отключает доступ к GPU.

**`NVIDIA_DRIVER_CAPABILITIES`** — переменная, определяющая набор загружаемых библиотек драйвера (`compute`, `utility`, `graphics`, `video`, `display`). Минимальный набор для inference — `compute,utility`.

## Предварительные требования

### На хосте
- **ОС:** Linux (Ubuntu 22.04+/24.04+/26.04, RHEL 8/9, Debian 12, SLES 15) с ядром 5.15+
- **GPU:** NVIDIA GPU с поддержкой CUDA (Compute Capability 5.0+ для CUDA 12+, 6.0+ для CUDA 13+)
- **Драйвер NVIDIA:** Установлен на хосте, версия >= 525.60.13 (для CUDA 12.x) или >= 580 (для CUDA 13.x). Проверка: `nvidia-smi`.
- **Docker Engine:** 29.x+, установлен из официального репозитория (см. [Установка Docker Engine на Ubuntu](../../Docker/docker_install_ubuntu.md)).
- **NVIDIA Container Toolkit:** 1.20.1+, установлен на хосте (см. [Установка NVIDIA Container Toolkit](../../Docker/docker_install_ubuntu.md#установка-nvidia-container-toolkit-gpu)).

### В образе
- **Base image:** `nvidia/cuda:<версия>-<вариант>-<os>` с CUDA, совместимой с драйвером хоста.
- **Фреймворки (опционально):** Официальные образы `pytorch/pytorch`, `tensorflow/tensorflow` уже содержат CUDA/cuDNN — не ставьте CUDA поверх них вручную.

## Основные концепции

### Стек: драйвер → toolkit → образ

Ключевой принцип: **драйвер GPU — на хосте, CUDA Toolkit — в образе**. Контейнер не содержит и не может содержать драйвер ядра; он содержит только userspace-библиотеки CUDA, совместимые с драйвером хоста.

```
Хост:  NVIDIA Driver (>= минимума для версии CUDA)  →  NVIDIA Container Toolkit (CDI)
                                                              │
Образ:  CUDA Toolkit (nvidia/cuda)  +  фреймворк (PyTorch/TF)  +  приложение
```

- CUDA 12.x требует драйвер хоста >= 525.60.13; CUDA 13.x требует драйвер >= 580 (точная матрица — в [CUDA Compatibility Guide](https://docs.nvidia.com/deploy/cuda-compatibility/)).
- Несовпадение версии драйвера хоста и CUDA в образе — самая частая причина «GPU не виден».

### Два механизма доступа к GPU

| Механизм | Как работает | Статус |
| :--- | :--- | :--- |
| **NVIDIA runtime (legacy)** | `nvidia-container-runtime` + `nvidia-container-runtime-hook` инжектят устройства и библиотеки; активируется флагом `--gpus` | Устаревший, но работает |
| **CDI (рекомендуемый)** | Runtime читает CDI-спецификацию (`/etc/cdi/nvidia.yaml`) и монтирует устройства; активируется `--device nvidia.com/gpu=all` | Современный стандарт, совместим с rootless |

CDI рекомендуется, потому что: (1) работает с любым CDI-aware runtime, не только Docker; (2) совместим с rootless-режимом; (3) явно декларирует устройства в спецификации, которую можно аудитировать.

### Варианты CUDA-образов (`nvidia/cuda`)

| Вариант | Содержимое | Размер (ubuntu24.04) | Когда использовать |
| :--- | :--- | :--- | :--- |
| `base` | CUDA runtime-библиотеки | ~190 МБ | Запуск готового CUDA-приложения |
| `runtime` | base + cuBLAS, cuFFT, cuSPARSE, cuRAND | ~1 ГБ | Inference, HPC-приложения |
| `devel` | runtime + заголовки, `nvcc`, компилятор | ~4.4 ГБ | Сборка CUDA-приложений (builder-стейдж) |
| `cudnn-runtime` | runtime + cuDNN | ~2.1 ГБ | Deep learning inference |
| `cudnn-devel` | devel + cuDNN | ~4.4 ГБ | Обучение моделей (builder-стейдж) |

Теги: `nvidia/cuda:<версия>-<вариант>-<os>`, например `13.4.0-cudnn-runtime-ubuntu24.04`. LTS-ветка CUDA 12 — `12.9.2-*`. Образы доступны для `ubuntu26.04/24.04/22.04` и `ubi9/ubi8`. Ubuntu 20.04 убрана начиная с CUDA 13.2.

### Переменные окружения CUDA-образов

CUDA-образы NVIDIA задают `NVIDIA_VISIBLE_DEVICES=all` и `NVIDIA_DRIVER_CAPABILITIES=compute,utility` по умолчанию. Для inference достаточно `compute,utility`; добавляйте `graphics`/`video`/`display` только при рендеринге или видеокодировании — каждая лишняя capability тянет дополнительные библиотеки драйвера.

## Практические сценарии

### Сценарий 1: Выбор CUDA base image

**Задача:** собрать образ для CUDA-приложения, не раздувая его.

```dockerfile
# Inference: только runtime-библиотеки, без компилятора
FROM nvidia/cuda:13.4.0-runtime-ubuntu24.04
COPY my-cuda-app /usr/local/bin/
CMD ["my-cuda-app"]
```

Для сборки CUDA-приложения из исходников — `devel` в builder-стейдже, `runtime` в финальном (см. сценарий 2).

### Сценарий 2: Multi-stage ML-сборка (devel → runtime)

**Задача:** обучить/скомпилировать модель с CUDA, но доставить в production только runtime.

```dockerfile
# syntax=docker/dockerfile:1
# Stage 1: сборка с полным CUDA-devel и cuDNN
FROM nvidia/cuda:13.4.0-cudnn-devel-ubuntu24.04 AS builder
WORKDIR /build
COPY . .
RUN make -j$(nproc) && ./train_model.sh

# Stage 2: runtime без компилятора и заголовков
FROM nvidia/cuda:13.4.0-cudnn-runtime-ubuntu24.04
WORKDIR /app
COPY --from=builder /build/model.bin /app/model.bin
COPY --from=builder /build/my-app /usr/local/bin/my-app
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
CMD ["my-app", "--model", "/app/model.bin"]
```

Почему: `devel`-образ (~4.4 ГБ) нужен только на этапе сборки; в production достаточно `cudnn-runtime` (~2.1 ГБ). Экономия — ~2.3 ГБ на образ.

### Сценарий 3: CDI — генерация спецификации и запуск

**Задача:** настроить доступ к GPU через CDI (современный стандарт).

```bash
# 1. Установить NVIDIA Container Toolkit на хосте — см.
#    [Установка NVIDIA Container Toolkit](../../Docker/docker_install_ubuntu.md)

# 2. Сгенерировать CDI-спецификацию (один раз на хосте)
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml

# 3. Проверить доступные CDI-устройства
nvidia-ctk cdi list
# → nvidia.com/gpu=all
# → nvidia.com/gpu=gpu0
# → nvidia.com/gpu=mig0g0  (если настроен MIG)

# 4. Запустить контейнер с GPU через CDI
docker run --rm --device nvidia.com/gpu=all nvidia/cuda:13.4.0-base-ubuntu24.04 nvidia-smi
```

CDI-спецификация автоматически обновляется службой `nvidia-cdi-refresh` при изменении драйвера или MIG-конфигурации (кроме снятия драйвера и реконфигурации MIG — там регенерация вручную).

### Сценарий 4: PyTorch / TensorFlow паттерн

**Задача:** образ для deep learning с фреймворком.

```dockerfile
# Inference-сервер на PyTorch
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
EXPOSE 8080
CMD ["python", "serve.py"]
```

Для обучения — образ с `-devel`/`-devel`-вариантом фреймворка; для inference — `-runtime`-вариант. Официальные образы фреймворков (`pytorch/pytorch`, `tensorflow/tensorflow`) уже включают совместимую CUDA и cuDNN — не устанавливайте CUDA вручную поверх них. Актуальные теги фреймворков — на [Docker Hub pytorch/pytorch](https://hub.docker.com/r/pytorch/pytorch/tags) и [tensorflow/tensorflow](https://hub.docker.com/r/tensorflow/tensorflow/tags).

### Сценарий 5: Model serving (Triton Inference Server)

**Задача:** сервер инференса моделей.

```dockerfile
# Triton — готовый сервер инференса от NVIDIA
FROM nvcr.io/nvidia/tritonserver:24.01-py3
WORKDIR /models
COPY models/ /models/
EXPOSE 8000 8001 8002
CMD ["tritonserver", "--model-repository=/models"]
```

Triton поддерживает TensorRT, PyTorch, TensorFlow, ONNX, OpenVINO. Порты: 8000 (HTTP), 8001 (gRPC), 8002 (metrics). Актуальные теги — на [NGC tritonserver](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/tritonserver). Пример NUMA-изолированного ML-инференса с GPU в Kubernetes — в [Topology Manager: сценарий 3](../../Kubernetes/Scheduling/topology_manager.md).

### Сценарий 6: MIG (Multi-Instance GPU)

**Задача:** изолировать несколько нагрузок на одном GPU.

```bash
# Запрос конкретного MIG-инстанса через CDI
docker run --rm --device nvidia.com/gpu=mig0g0 my-ml-app
```

MIG доступен на GPU Ampere (A100) и новее. Каждый MIG-инстанс — изолированная доля GPU (память, SM). В Kubernetes — через `nvidia.com/mig-1g.5gb` resource (см. [Device Manager](../../Kubernetes/Scheduling/device_manager.md)).

### Сценарий 7: Сжатие слоёв в ZSTD (ускорение pull-а)

**Задача:** сократить время скачивания и экстракции больших GPU-образов (Triton ~20 ГБ) при автоскейлинге.

```bash
# Сборка и пуш образа со слоями в ZSTD вместо GZIP (по умолчанию)
docker buildx build \
  --output type=image,name=<registry>/<image>,push=true,compression=zstd .
# → слои в реестре: application/vnd.oci.image.layer.v1.tar+zstd
```

`compression` принимает `uncompressed`/`gzip`/`estargz`/`zstd`; `compression-level` — 0–22 для zstd (3–6 — default); `force-compression=true` пережимает слои, унаследованные от базового образа. На практике (замер из доклада про GPU-инференс): pull образа Triton сократился с 6,5 до 2 минут. Подробнее — в [GPU-инференс: автоскейлинг](../../Kubernetes/Autoscaling/gpu_inference_autoscaling.md).

## Операции и команды

| Команда | Описание |
| :--- | :--- |
| `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` | Сгенерировать CDI-спецификацию |
| `nvidia-ctk cdi list` | Список доступных CDI-устройств |
| `sudo nvidia-ctk config --in-place --set nvidia-container-runtime.mode=cdi` | Принудительный CDI-режим runtime |
| `docker run --device nvidia.com/gpu=all <img> nvidia-smi` | Запуск с GPU (CDI) |
| `docker run --gpus all <img> nvidia-smi` | Запуск с GPU (legacy `--gpus`) |
| `docker run -e NVIDIA_VISIBLE_DEVICES=void <img>` | Отключить GPU в контейнере |
| `nvidia-smi` | Проверка GPU внутри контейнера |
| `nvidia-ctk runtime configure --runtime=docker` | Зарегистрировать nvidia-runtime в Docker daemon.json |
| `nvidia-ctk runtime configure --runtime=docker --set-as-default` | Сделать nvidia runtime дефолтным |

## Валидация

### Проверка работоспособности GPU в контейнере
```bash
# Базовая проверка: GPU виден и nvidia-smi работает
docker run --rm --device nvidia.com/gpu=all nvidia/cuda:13.4.0-base-ubuntu24.04 nvidia-smi
# → таблица GPU хоста с UUID, памятью, драйвером

# Проверка CUDA runtime
docker run --rm --device nvidia.com/gpu=all nvidia/cuda:13.4.0-runtime-ubuntu24.04 nvidia-smi
# → CUDA Version: 13.4 (должен совпадать с тегом образа)

# Проверка cuDNN (если используется cudnn-вариант)
docker run --rm --device nvidia.com/gpu=all nvidia/cuda:13.4.0-cudnn-runtime-ubuntu24.04 \
  bash -c 'cat /usr/include/cudnn_version.h | grep CUDNN_MAJOR'
# → #define CUDNN_MAJOR 9
```

### Проверка CDI-спецификации
```bash
# Список CDI-устройств
nvidia-ctk cdi list
# → nvidia.com/gpu=all
# → nvidia.com/gpu=gpu0
# → nvidia.com/gpu=mig0g0  (если MIG настроен)

# Проверка файла спецификации
cat /etc/cdi/nvidia.yaml | head -30
# → kind: cdi.cncf.io/v1
# → devices: ...
```

### Проверка совместимости драйвер/CUDA
```bash
# Версия драйвера на хосте
nvidia-smi | head -1
# → NVIDIA-SMI 580.xx.xx  Driver Version: 580.xx.xx  CUDA Version: 13.4

# Требуемый минимум для CUDA в образе (см. CUDA Compatibility Guide):
# CUDA 12.x → драйвер >= 525.60.13
# CUDA 13.x → драйвер >= 580
```

## Разрешение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `nvidia-smi` в контейнере пуст / `CUDA error: no kernel image` | Драйвер хоста старше, чем требует CUDA в образе | Обновить драйвер хоста или понизить CUDA в образе (CUDA 12.x → драйвер >= 525; CUDA 13.x → драйвер >= 580) |
| `CUDA error: no CUDA-capable device is detected` | GPU не проброшен | `--device nvidia.com/gpu=all` (CDI) или `--gpus all` (legacy) |
| `cdi spec not found` / `no CDI device` | CDI-спецификация не сгенерирована | `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` |
| GPU виден, но приложение падает | `NVIDIA_DRIVER_CAPABILITIES` не включает нужную библиотеку | Добавить `graphics`/`video`/`display` при рендеринге |
| Rootless-режим: GPU недоступен | Legacy runtime несовместим с rootless | Использовать CDI (`--device nvidia.com/gpu=...`) |
| MIG-инстанс не найден | MIG не настроен на GPU | Настроить MIG на хосте, регенерировать CDI |
| `Error response from daemon: could not select device driver "" with capabilities: [[gpu]]` | Docker daemon не знает о nvidia-runtime | Выполнить `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker` |

Диагностика GPU на хосте (не в контейнере) — в [GPU-диагностика](../../Linux/Diagnostics/Hardware/gpu_diagnostics.md).

## Best Practices

- **Закрепляйте версию CUDA** (`13.4.0-*` или LTS `12.9.2-*`), не `latest` — воспроизводимость и совместимость с драйвером.
- **`runtime` для inference, `devel` только для сборки** — multi-stage, чтобы не тащить компилятор в production.
- **CDI вместо `--gpus`** — современный стандарт, совместим с rootless и не-Docker runtime.
- **Минимальный `NVIDIA_DRIVER_CAPABILITIES`** — `compute,utility` для inference; не добавляйте `graphics`/`video` без необходимости.
- **Официальные образы фреймворков** (`pytorch/pytorch`, `tensorflow/tensorflow`) — уже содержат совместимую CUDA/cuDNN; не ставьте CUDA вручную поверх.
- **Проверяйте совместимость драйвера хоста и CUDA** перед выбором тега — самая частая ошибка (CUDA 12.x → драйвер >= 525; CUDA 13.x → драйвер >= 580).
- **В Kubernetes** — GPU-нагрузки планируются через `nodeAffinity`/`tolerations`/`resources: nvidia.com/gpu` (см. [Affinity: GPU](../../Kubernetes/Scheduling/affinity.md), [Taints and Tolerations: GPU](../../Kubernetes/Scheduling/taints_and_tolerations.md)).
- **Мониторинг GPU в контейнерах** — используйте DCGM exporter (см. [GPU-диагностика: интеграция с Prometheus](../../Linux/Diagnostics/Hardware/gpu_diagnostics.md#интеграция-с-prometheus-dcgm-exporter-для-nvidia)).
- **Rootless + GPU** — требует CDI и настройки `nvidia-ctk runtime configure --runtime=docker --config=$HOME/.config/docker/daemon.json` (см. [Rootless-режим в docker_install_ubuntu.md](../../Docker/docker_install_ubuntu.md#настройка-rootless-режима)).

## Дополнительная информация

- **[Установка NVIDIA Container Toolkit](../../Docker/docker_install_ubuntu.md#установка-nvidia-container-toolkit-gpu)** — установка toolkit на хосте (пререквизит для CDI и `--gpus`).
- **[Практические сценарии инструкций: современные рантаймы (GPU, Wasm, CDI)](Instructions/practical_scenarios.md)** — краткий пример CDI.
- **[GPU-диагностика](../../Linux/Diagnostics/Hardware/gpu_diagnostics.md)** — диагностика GPU на хосте, DCGM-exporter, мониторинг в Prometheus.
- **[Topology Manager: NUMA-изолированный ML-инференс](../../Kubernetes/Scheduling/topology_manager.md)** — GPU + NUMA в Kubernetes.
- **[Device Manager](../../Kubernetes/Scheduling/device_manager.md)** — GPU/MIG как расширенные ресурсы в Kubernetes.
- **[Шеринг GPU в Kubernetes](../../Kubernetes/Scheduling/gpu_sharing.md)** — time-slicing, MPS, MIG, HAMi, dynamic MIG.
- **[GPU-инференс: автоскейлинг](../../Kubernetes/Autoscaling/gpu_inference_autoscaling.md)** — ускорение деплоя (ZSTD, lazy loading, кэш образов).
- **[Container Device Interface (CDI)](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html)** — спецификация CDI от NVIDIA.
- **[CUDA Compatibility Guide](https://docs.nvidia.com/deploy/cuda-compatibility/)** — матрица совместимости драйверов и версий CUDA.
- **[NVIDIA Container Toolkit Releases](https://github.com/NVIDIA/nvidia-container-toolkit/releases)** — changelog и версии toolkit.
- **[nvidia/cuda Docker Hub](https://hub.docker.com/r/nvidia/cuda/tags)** — все доступные теги CUDA-образов.
