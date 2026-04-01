# Talos: Локальный кластер Kubernetes

## Определения

**Talos Linux** — современная, безопасная и минималистичная ОС для запуска Kubernetes. Управляется исключительно через API, что исключает SSH и обеспечивает предсказуемость конфигурации (immutable infrastructure).

**`talosctl`** — CLI-утилита для взаимодействия с Talos через gRPC API. Позволяет разворачивать локальные кластеры, используя Docker для запуска узлов.

**Machine Config** — декларативный YAML-файл, определяющий конфигурацию каждого узла Talos (role, network, extensions).

## Основные концепции

### Архитектура Talos

| Компонент | Описание |
| :--- | :--- |
| **Immutable OS** | Только необходимые компоненты, read-only корневая ФС |
| **API-First** | Все операции через gRPC API, SSH отсутствует |
| **Security by Default** | mTLS для всех соединений, автоматическая ротация сертификатов |
| **Containerized Nodes** | Узлы запускаются как Docker-контейнеры (локальный режим) |

### Сравнение с аналогами

| Инструмент | Подход | Безопасность | Сложность |
| :--- | :--- | :--- | :--- |
| **[kind](./kind/kind_concepts.md)** | Контейнеры с стандартным K8s | Стандартная | Низкая |
| **talosctl** | Контейнеры с Talos OS | mTLS, immutable | Средняя |
| **minikube** | VM с стандартным K8s | Стандартная | Низкая |

### Рабочий процесс talosctl

1. **Генерация конфигурации** — создание machine configs для control-plane и worker
2. **Запуск контейнеров** — Docker-контейнеры с Talos OS
3. **Bootstrapping кластера** — инициализация через `talosctl bootstrap`
4. **Автоматический kubeconfig** — обновление `~/.kube/config` и `~/.talos/config`

## Практические сценарии

### Подготовка

**Требования:**

- Docker 18.03+
- Linux/macOS/Windows (WSL2)

**Установка talosctl:**

```bash
# Автоматическая установка
curl -sL https://talos.dev/install | sh

# Перемещение в PATH
sudo mv talosctl /usr/local/bin/

# Проверка
talosctl version
```

### Создание кластера

**Базовый кластер (1 control-plane + 1 worker):**

```bash
talosctl cluster create --name talos-default --wait
```

**Параметры:**

- `--name` — имя кластера (по умолчанию `talos-default`)
- `--wait` — ждать готовности кластера
- `--workers N` — количество worker-узлов
- `--masters N` — количество control-plane узлов (для HA)

**Кастомизация:**

```bash
# HA кластер с 3 control-plane и 3 worker
talosctl cluster create --name ha-cluster --masters 3 --workers 3 --wait

# С конкретной версией Talos
talosctl cluster create --image ghcr.io/siderolabs/kubelet:v1.31.0
```

### Работа с kubeconfig

talosctl автоматически обновляет конфигурацию после создания кластера:

```bash
# Проверка контекста
kubectl config get-contexts
kubectl config use-context talos-talos-default

# Статус узлов
kubectl get nodes

# Развертывание приложения
kubectl run nginx --image=nginx:1.27
kubectl expose pod nginx --port=80 --type=NodePort
```

### Использование talosctl

**Dashboard (веб-интерфейс):**

```bash
talosctl dashboard
```

**Просмотр сервисов:**

```bash
# Список сервисов Talos
talosctl services

# Статус конкретного сервиса
talosctl service k8s
```

**Контейнеры:**

```bash
# Запущенные контейнеры (K8s namespace)
talosctl containers -k

# Логи контейнера
talosctl logs -k <pod-name>
```

**Файловая система:**

```bash
# Копирование файлов из узла
talosctl copy <node-ip>:/var/log/pods /tmp/logs

# Копирование файлов в узел
talosctl copy /path/to/config <node-ip>:/etc/config
```

**Перезагрузка/остановка:**

```bash
# Перезагрузка узла
talosctl reboot -n <node-ip>

# Остановка узла
talosctl shutdown -n <node-ip>
```

### Машинные конфиги (расширенная конфигурация)

**Генерация конфигов:**

```bash
# Генерация для bare-metal
talosctl gen config talos-default https://192.168.1.100:6443

# Файлы: controlplane.yaml, worker.yaml, talosconfig
```

**Пример machine config с extensions:**

```yaml
# custom-config.yaml
machine:
  type: controlplane
  kernel:
    extraArgs:
      net.ifnames: "0"
  network:
    interfaces:
      - interface: eth0
        addresses:
          - 192.168.1.10/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.1.1
        nameservers:
          - 8.8.8.8
  sysctls:
    net.ipv4.ip_forward: "1"
cluster:
  clusterName: talos-default
  controlPlane:
    endpoint: https://192.168.1.100:6443
```

### Уничтожение кластера

```bash
# Удаление конкретного кластера
talosctl cluster destroy --name talos-default

# Удаление кластера по умолчанию
talosctl cluster destroy
```

## Дополнительная информация

### Версии и совместимость

| Talos Version | Kubernetes | Статус |
| :--- | :--- | :--- |
| 1.9.x | 1.31 | Актуальная |
| 1.8.x | 1.30 | Поддерживается |
| 1.7.x | 1.29 | Поддерживается |

### Безопасность

- **mTLS** — все соединения зашифрованы
- **Автоматическая ротация** — сертификаты обновляются автоматически
- **No SSH** — исключает атаки через SSH
- **Immutable FS** — защита от модификации

### Интеграция с CI/CD

**GitHub Actions пример:**

```yaml
- name: Setup Talos
  uses: siderolabs/talos-action@v1
  with:
    cluster-name: 'test-cluster'
    talos-version: 'v1.9.0'
    kubernetes-version: 'v1.31.0'
```

### Расширения Talos

Talos поддерживает system extensions для дополнительной функциональности:

- **QEMU Guest Agent** — для виртуализации
- **NVIDIA GPU** — поддержка GPU
- **WireGuard** — VPN

Подробнее в [официальной документации](https://www.talos.dev/) и [GitHub](https://github.com/siderolabs/talos). Для генерации конфигов используйте [Machine Config Generator](https://www.talos.dev/config/).

Альтернативные решения для локальных кластеров: [kind](./kind/kind_concepts.md) (стандартный K8s в контейнерах). Работа с контекстами описана в [kubeconfig и подключение](../Operations/kubeconfig_and_connection.md), архитектура Control Plane — в [Control Plane архитектура](../Concepts/control_plane_architecture.md).
