# Minikube: Определения и концепции

## Определения

**Minikube** — инструмент для запуска локального однонодового кластера **K8s (Kubernetes)** на рабочей машине. Предназначен для разработки, тестирования и обучения. Minikube разворачивает полноценный, но упрощённый кластер Kubernetes внутри **VM (Virtual Machine — виртуальная машина)**, Docker-контейнера или на bare metal.

**container runtime** — программа для запуска и управления контейнерами (Docker, containerd, CRI-O). Обязательный компонент для работы Minikube.

> **Связанные определения:**
>
> - **[kubeconfig](../../Operations/kubeconfig_and_connection.md)** — файл конфигурации для подключения к Kubernetes
> - **[kubectl](../../kubernetes_overview.md)** — **CLI (Command Line Interface)** утилита для управления кластером

---

## Базовые концепции

### Архитектура Minikube

| Компонент | Описание |
| :--- | :--- |
| **Однонодовый кластер** | Один узел control-plane (worker) — достаточно для изучения K8s |
| **Виртуализация** | Запускается в VM, Docker-контейнере или на bare metal |
| **Автоматическая настройка** | Minikube сам скачивает образы, настраивает kubeconfig |
| **Интеграция с kubectl** | Команды выполняются через `minikube kubectl -- <command>` |

### Поддержка версий

Minikube поддерживает последнюю версию Kubernetes и 6 предыдущих минорных версий.
> **Примечание:** Версии **v1.33** и ниже достигли **EOL (End of Life)**. Актуальные образы проверяйте в [release notes](https://github.com/kubernetes/minikube/releases).

---

### Требования и зависимости

| Компонент | Назначение | Проверка |
| :--- | :--- | :--- |
| **Docker Desktop** (или другой runtime) | Среда исполнения контейнеров | `docker system info` |
| **Minikube** | Инструмент развёртывания кластера | `minikube version` |
| **kubectl** (опционально) | CLI для управления K8s | `kubectl version --client` |

> **Примечание:** Если kubectl не установлен, используйте встроенную версию: `minikube kubectl -- <command>`

### Системные требования

| Ресурс | Минимум | Рекомендовано |
| :--- | :--- | :--- |
| **CPU (Central Processing Unit)** | 2 ядра | 4 ядра и более |
| **Память (RAM)** | 4 ГБ | 8–16 ГБ |
| **Диск** | 20 ГБ | 50 ГБ и более |

---

### Сравнение с аналогами

| Инструмент | Подход | Безопасность | Сложность | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| **[kind](../kind/kind_concepts.md)** | Контейнеры с стандартным K8s | Стандартная | Низкая | CI/CD, тестирование |
| **[talosctl](../local_cluster_with_talosctl.md)** | Контейнеры с Talos OS | mTLS, immutable | Средняя | Безопасные кластеры |
| **minikube** | VM с стандартным K8s | Стандартная | Низкая | Локальная разработка |

**Преимущества Minikube:**

- Полнофункциональная VM с реальным K8s
- Поддержка множества драйверов (Docker, VirtualBox, KVM, Hyperkit)
- Встроенные аддоны (dashboard, ingress, metrics-server, registry)
- Кроссплатформенность (Linux, macOS, Windows)

**Ограничения Minikube:**

- Тяжелее аналогов (особенно при использовании VM-драйверов вместо контейнерных)
- Не предназначен для production-окружений (ориентирован на локальную разработку и тесты)

---

### kubeconfig и контексты

Minikube автоматически управляет конфигурацией подключения:

1. **При запуске** (`minikube start`) создаётся запись в `~/.kube/config`
2. **Контекст** называется `minikube` по умолчанию
3. **kubectl** автоматически использует этот контекст

**Проверка контекста:**

```bash
kubectl config current-context
# → minikube

kubectl config get-contexts
# Список всех доступных контекстов
```

**Использование встроенного kubectl:**

```bash
# Если kubectl не установлен
minikube kubectl -- get nodes

# Проверка состояния кластера
minikube kubectl -- get pods -A
```

---

### Драйверы Minikube

Minikube поддерживает различные драйверы для запуска кластера:

| Драйвер | Платформа | Требования | Примечание |
| :--- | :--- | :--- | :--- |
| **docker** | Linux/macOS/Windows | Docker Engine или Docker Desktop | Рекомендуемый драйвер по умолчанию |
| **vfkit / qemu2** | macOS | vfkit, qemu | Современные драйверы для macOS (Apple Silicon и Intel) |
| **virtualbox** | Linux/macOS/Windows | VirtualBox | Классический VM-драйвер |
| **kvm2** | Linux | KVM, libvirt | Лучшая производительность VM на Linux |
| **hyper-v** | Windows | Hyper-V | Нативный гипервизор Windows |
| **hyperkit** | macOS | Hyperkit | *Устаревший (legacy)* драйвер для старых версий macOS |
| **none** | Linux | Bare metal, Docker (deb-пакет), root | Работает прямо на хосте, небезопасно для других сервисов |

**Автоматический выбор драйвера:**

Minikube автоматически определяет доступный драйвер в системе. Если установлен Docker — будет выбран `docker`. Явное указание через `--driver` не требуется.

**Драйвер none (bare metal):**

Запускает компоненты Kubernetes напрямую на хост-системе без виртуализации.

- **Требования:** только Linux, Docker установлен как **deb-пакет** (snap-пакет не работает), root-привилегии
- **Предупреждение:** устанавливает kubelet, kube-apiserver и другие компоненты на хост. Может конфликтовать с существующими сервисами.
- **Не рекомендуется** для продакшн-окружений

**Проблема со snap-пакетом:**

На Debian и производных (Ubuntu) **snap-пакет Docker не работает** с Minikube. Необходимо использовать Docker из официального deb-репозитория.

**Выбор драйвера:**

```bash
# Запуск с конкретным драйвером
minikube start --driver=docker

# Установка драйвера по умолчанию
minikube config set driver docker
```

---

### Сеть и сервисы типа LoadBalancer

По умолчанию облачные провайдеры предоставляют внешний IP-адрес для сервисов типа `LoadBalancer`. В локальной среде (Minikube) такие сервисы остаются в состоянии `<pending>`.

Для решения этой проблемы используется команда `minikube tunnel`:
- Она запускается как фоновый процесс с правами администратора.
- Создаёт сетевой маршрут на хост-машине к CIDR-блоку кластера.
- Назначает внешний IP-адрес для сервисов `LoadBalancer`, делая их доступными с хоста.

---

### Аддоны

Minikube включает набор встроенных аддонов для расширения функциональности:

| Аддон | Назначение |
| :--- | :--- |
| **dashboard** | Веб-интерфейс управления K8s |
| **ingress** | Ingress-контроллер (NGINX) для маршрутизации |
| **metrics-server** | Сбор метрик (необходим для `kubectl top`) |
| **registry** | Локальный Docker Registry |
| **storage-provisioner** | Автоматическое создание **PV (Persistent Volume)** (включён по умолчанию) |
| **metallb** | Реализация LoadBalancer для bare metal и локальных сред |
| **istio** | Service mesh для управления сетевым трафиком |
| **inspektor-gadget** | Набор инструментов для отладки и инспекции кластера (eBPF) |

**Управление аддонами:**

```bash
# Список доступных аддонов
minikube addons list

# Включение аддона
minikube addons enable ingress

# Отключение аддона
minikube addons disable registry
```

---

## Практические сценарии

### Основные команды Minikube

| Команда | Описание |
| :--- | :--- |
| `minikube start` | Запуск кластера |
| `minikube stop` | Остановка кластера (без удаления) |
| `minikube delete` | Удаление кластера и всех данных |
| `minikube pause` / `unpause` | Приостановка и возобновление работы K8s (полезно для экономии ресурсов) |
| `minikube status` | Проверка состояния кластера |
| `minikube kubectl -- <cmd>` | Выполнение команд kubectl |
| `minikube dashboard` | Открытие Kubernetes Dashboard |
| `minikube ip` | IP-адрес кластера |
| `minikube ssh` | Подключение к узлу по SSH |
| `minikube tunnel` | Проброс сети для сервисов типа LoadBalancer |
| `minikube mount` | Проброс директории с хоста внутрь Minikube |
| `minikube docker-env` | Настройка Docker CLI хоста на использование Docker-демона внутри Minikube |

Подробные примеры использования см. в файле **[Практические сценарии](./minikube_practical_scenarios.md)**.

---

## Дополнительная информация

- **Официальная документация:** [minikube.sigs.k8s.io](https://minikube.sigs.k8s.io/docs/)
- **GitHub:** [kubernetes/minikube](https://github.com/kubernetes/minikube)
- **Установка Docker Desktop:** [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
- **Практические сценарии:** [minikube_practical_scenarios.md](./minikube_practical_scenarios.md)
