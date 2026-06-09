# Установка локального кластера Kubernetes через Talos Linux

Руководство по развертыванию локального кластера Kubernetes с использованием Talos Linux и утилиты `talosctl` в Docker-контейнерах.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Talos Linux** | Современная, безопасная и минималистичная ОС для запуска Kubernetes. Управляется исключительно через API, не имеет SSH и использует иммутабельную (immutable) файловую систему. |
| **talosctl** | CLI-утилита для взаимодействия с API Talos Linux. Позволяет управлять кластером, узлами и разворачивать локальные окружения. |
| **Machine Config** | Декларативный YAML-файл, определяющий конфигурацию узла Talos (роль, сетевые настройки, расширения). |

---

## Основные концепции

### Архитектура Talos Linux

Talos Linux спроектирована специально для Kubernetes. Основные принципы:

- **API-First**: Все управление узлом (даже на уровне ОС) происходит через gRPC API.
- **Immutable OS**: Корневая файловая система доступна только для чтения, что предотвращает несанкционированные изменения.
- **Security by Default**: По умолчанию используется mTLS для всех соединений и автоматическая ротация сертификатов.
- **No SSH**: Отсутствие оболочки (shell) и SSH минимизирует поверхность атаки.

### Сравнение с аналогами

| Инструмент | Подход | Безопасность | Сложность |
| :--- | :--- | :--- | :--- |
| **kind** | Стандартный K8s в контейнерах | Стандартная | Низкая |
| **talosctl** | Контейнеры с Talos OS | Высокая (mTLS, immutable) | Средняя |
| **minikube** | Стандартный K8s в VM/контейнерах | Стандартная | Низкая |

### Рабочий процесс talosctl

1. **Генерация конфигурации**: Создание machine configs для Control Plane и Worker узлов.
2. **Запуск контейнеров**: Развертывание Docker-контейнеров, имитирующих физические или виртуальные узлы с Talos OS.
3. **Инициализация (Bootstrapping)**: Запуск процесса создания кластера через API.
4. **Настройка доступа**: Автоматическое обновление `kubeconfig` и `talosconfig`.

---

## Практические сценарии

### Подготовка окружения

**Требования:** Docker и установленная утилита `talosctl`.

```bash
# Установка talosctl
curl -sL https://talos.dev/install | sh
sudo mv talosctl /usr/local/bin/

# Проверка установки
talosctl version
```

### Создание кластера

Для локальной разработки достаточно создать кластер из нескольких узлов в Docker.

```bash
# Базовый кластер (1 Master + 1 Worker)
talosctl cluster create --name dev-cluster --wait

# HA кластер (3 Masters + 3 Workers)
talosctl cluster create --name ha-cluster --masters 3 --workers 3 --wait
```

### Управление через talosctl

Утилита предоставляет расширенные возможности по управлению ОС и Kubernetes.

```bash
# Просмотр статуса сервисов на узлах
talosctl services

# Доступ к интерактивной панели управления (Dashboard)
talosctl dashboard

# Просмотр логов контейнеров Kubernetes
talosctl logs -k <pod-name>

# Копирование файлов с узла
talosctl copy <node-ip>:/var/log/pods /tmp/logs
```

### Работа с конфигурацией узлов

Генерация конфигурации для реальных серверов (Bare Metal или VM):

```bash
# Генерация файлов конфигурации
talosctl gen config talos-default https://<load-balancer-ip>:6443

# Применение конфигурации к узлу
talosctl apply-config --insecure --nodes <node-ip> --file controlplane.yaml
```

### Удаление кластера

```bash
talosctl cluster destroy --name dev-cluster
```

---

## Дополнительная информация

### Совместимость версий

| Версия Talos | Kubernetes | Статус |
| :--- | :--- | :--- |
| 1.9.x | 1.31 | Актуальная |
| 1.8.x | 1.30 | Поддерживается |

### Расширения системы (Extensions)

Talos поддерживает расширения для специфических задач:

- **QEMU Guest Agent**: Для работы в виртуализации.
- **NVIDIA GPU**: Для задач машинного обучения.
- **WireGuard**: Для защищенных сетевых соединений.

### См. также

- [Создание локальных кластеров через kind](./kind/kind_concepts.md)
- [Архитектура Control Plane](../Concepts/control_plane_architecture.md)
- [Управление kubeconfig и подключение](../Operations/kubeconfig_and_connection.md)
