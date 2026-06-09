# Minikube: Практические сценарии

## Определения

**Minikube** — инструмент для запуска локального однонодового кластера **K8s (Kubernetes)**. Используется для разработки, тестирования и обучения.

Подробные определения и описание архитектуры см. в **[Minikube: Определения и концепции](./minikube_concepts.md)**.

---

## Базовые концепции

### Предварительные требования

Перед началом работы убедитесь, что система соответствует требованиям:

- **Аппаратные ресурсы и поддержка версий:** см. в **[Minikube: Определения и концепции](./minikube_concepts.md)**.
- **Драйвер и среда исполнения:** для работы Minikube на Linux рекомендуется использовать Docker. Инструкции по установке: **[Установка Docker на Ubuntu](../../../Docker/docker_install_ubuntu.md)**.

> **Важно:** Для стабильной работы рекомендуется выделить **VM (Virtual Machine — виртуальная машина)** минимум **4 ГБ RAM (Random Access Memory — оперативная память)**.

---

## Практические сценарии

### Установка Minikube

| **ОС (Операционная система)** | Команда |
| :--- | :--- |
| **macOS (Homebrew)** | `brew install minikube` |
| **Linux (binary)** | `curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && sudo install minikube-linux-amd64 /usr/local/bin/minikube` |
| **Windows (Chocolatey)** | `choco install minikube` |

**Проверка:** `minikube version`

### Установка kubectl (опционально)

Minikube включает встроенную версию **kubectl** — **CLI (Command Line Interface)** утилиты для управления кластером. Для установки отдельной версии:

| ОС | Команда |
| :--- | :--- |
| **macOS** | `brew install kubectl` |
| **Linux** | `curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl` |

**Проверка:** `kubectl version --client`

---

### Запуск кластера

#### Базовый запуск

```bash
minikube start
```

**Процесс:** автоматический выбор драйвера, скачивание образа узла, создание контейнера или VM, инициализация Kubernetes (включая настройку **PV/PVC — Persistent Volume / Persistent Volume Claim** через storage-provisioner) и настройка **kubeconfig**.

**Результат:** кластер запущен, kubectl настроен на контекст `minikube`.

> **Примечание:** Флаг `--driver=docker` необязателен. Подробнее о драйверах — в **[minikube_concepts.md](./minikube_concepts.md)**.

#### Запуск с драйвером none (bare metal)

```bash
minikube start --driver=none
```

**Особенности:** требует Linux и установки Docker через deb-пакет (не snap). Устанавливает компоненты K8s напрямую на хост-систему.

#### Запуск с параметрами

| Параметр | Команда |
| :--- | :--- |
| **Ресурсы** | `minikube start --cpus=4 --memory=8192mb` |
| **Версия K8s** | `minikube start --kubernetes-version=v1.33.0` |
| **Драйвер** | `minikube start --driver=virtualbox` |
| **Реестр** | `minikube start --insecure-registry="10.0.0.0/24"` |

### Проверка состояния

| Проверка | Команда |
| :--- | :--- |
| **Статус** | `minikube status` |
| **Узлы** | `kubectl get nodes` или `minikube kubectl -- get nodes` |
| **Пространства имен** | `kubectl get namespaces` |

---

### Работа с кластером

#### Развёртывание приложения

```bash
# Создание Deployment
kubectl create deployment nginx --image=nginx:1.27

# Проверка подов
kubectl get pods

# Экспонирование сервиса (NodePort)
kubectl expose deployment nginx --port=80 --type=NodePort

# Получение URL (Uniform Resource Locator) сервиса
minikube service nginx --url
```

#### Доступ к Dashboard и SSH

- **Веб-интерфейс:** `minikube dashboard` (открывает панель управления в браузере).
- **SSH (Secure Shell) доступ:** `minikube ssh` (подключение к узлу кластера).

#### Копирование файлов

```bash
# В кластер
minikube cp ./config.yaml /home/docker/config.yaml

# Из кластера
minikube cp /var/log/pods/mypod.log ./logs/
```

---

### Управление и аддоны

| Операция | Команда |
| :--- | :--- |
| **Остановка** | `minikube stop` |
| **Удаление** | `minikube delete` (флаг `--all` для всех профилей) |
| **Список аддонов** | `minikube addons list` |
| **Включение аддона** | `minikube addons enable <name>` |

**Популярные аддоны:** `ingress`, `metrics-server`, `registry`.

---

### Работа с образами Docker

#### Использование демона Minikube

Позволяет K8s видеть образы, собранные локально, без отправки в реестр.

```bash
# Переключение окружения
eval $(minikube docker-env)

# Сборка образа внутри Minikube
docker build -t myapp:1.0 .

# Использование в Deployment
kubectl create deployment myapp --image=myapp:1.0
```

---

### Multi-node конфигурация

```bash
# Запуск с 3 узлами
minikube start --nodes=3

# Управление узлами
minikube node add --worker
minikube node remove minikube-m03
```

---

### Отладка и мониторинг

- **Логи:** `kubectl logs <pod-name>` (флаг `-l app=name` для группы подов).
- **Описание:** `kubectl describe pod <pod-name>`.
- **Метрики:** `kubectl top nodes` (требуется аддон `metrics-server`).

### Типичные ошибки

| Ошибка | Решение |
| :--- | :--- |
| Docker не запущен | Запустить Docker Desktop или службу Docker |
| Ошибка подключения | Выполнить `minikube start` для восстановления сессии |
| Статус `Pending` | Недостаточно ресурсов (CPU/RAM). Увеличьте лимиты при старте |
| `ImagePullBackOff` | Образ недоступен. Проверьте имя или используйте `docker-env` |

---

## Дополнительная информация

### Рекомендации по поиску

При поиске специфических инструкций (например, для конкретной версии ОС) используйте уточняющие запросы, такие как `install minikube ubuntu 24.04`. Официальная документация может не учитывать особенности пакетных менеджеров конкретных дистрибутивов.

### Смотрите также

- **Официальный сайт:** [minikube.sigs.k8s.io](https://minikube.sigs.k8s.io/docs/)
- **Концепции и архитектура:** **[minikube_concepts.md](./minikube_concepts.md)**
- **GitHub репозиторий:** [kubernetes/minikube](https://github.com/kubernetes/minikube)
