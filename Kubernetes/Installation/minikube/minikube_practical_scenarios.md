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

> **Важно:** Для стабильной работы рекомендуется выделить **VM** минимум **4 ГБ RAM**.

---

## Практические сценарии

### Установка Minikube

| **ОС** | Команда |
| :--- | :--- |
| **macOS (Homebrew)** | `brew install minikube` |
| **Linux (binary)** | `curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && sudo install minikube-linux-amd64 /usr/local/bin/minikube` |
| **Windows (Chocolatey)** | `choco install minikube` |

**Проверка:** `minikube version`

### Установка kubectl (опционально)

Minikube включает встроенную команду `minikube kubectl`, которая позволяет выполнять команды без отдельной установки утилиты. Однако для полноценной работы рекомендуется установить `kubectl` в систему.

Инструкции по установке для всех ОС: [Установка kubectl](../kubectl_installation.md)

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
| **Версия K8s** | `minikube start --kubernetes-version=v1.36.0` |
| **Драйвер** | `minikube start --driver=virtualbox` |
| **Реестр** | `minikube start --insecure-registry="10.0.0.0/24"` |
| **Профиль** | `minikube start -p dev-cluster` |

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
# → deployment.apps/nginx created

# Проверка подов
kubectl get pods
# → NAME                     READY   STATUS    RESTARTS   AGE
# → nginx-6f8d...-xxxxx      1/1     Running   0          10s

# Экспонирование сервиса (NodePort)
kubectl expose deployment nginx --port=80 --type=NodePort
# → service/nginx exposed

# Получение URL сервиса
minikube service nginx --url
# → http://192.168.49.2:31234
```

#### Экспонирование сервиса (LoadBalancer)

При использовании типа сервиса `LoadBalancer`, необходимо запустить локальный туннель:

```bash
# Запуск туннеля (требует прав администратора)
minikube tunnel
# → Status:
# → machine: minikube
# → pid: 12345
# → route: 10.96.0.0/12 -> 192.168.49.2
# → minikube: Routing CIDR 10.96.0.0/12 to ...
```

После этого внешний IP-адрес сервиса станет доступен в `kubectl get svc`.

#### Доступ к Dashboard и SSH

- **Веб-интерфейс:** `minikube dashboard` (открывает панель управления в браузере).
- **SSH доступ:** `minikube ssh` (подключение к узлу кластера).

#### Копирование и монтирование файлов

```bash
# Копирование файла в кластер
minikube cp ./config.yaml /home/docker/config.yaml

# Копирование файла из кластера
minikube cp /var/log/pods/mypod.log ./logs/
```

**Монтирование директории с хоста:**

Позволяет пробросить локальную директорию напрямую в виртуальную машину кластера:

```bash
# Монтирование локальной папки в /data внутри Minikube
minikube mount /path/to/local/dir:/data
# → Mounting host path /path/to/local/dir into VM as /data ...
```
> Процесс будет заблокирован в терминале. Для остановки монтирования нажмите `Ctrl+C`.

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

В Minikube есть два основных способа работы с локальными образами: использование встроенного демона и прямая загрузка архивов.

#### Способ 1: Использование демона Minikube

Позволяет K8s видеть образы, собранные локально, без отправки во внешний реестр.

```bash
# Переключение окружения Docker CLI на демона внутри Minikube
eval $(minikube docker-env)

# Сборка образа (происходит прямо в кластере)
docker build -t myapp:1.0 .
# → Successfully tagged myapp:1.0

# Использование в Deployment (образ уже локально доступен узлу)
kubectl create deployment myapp --image=myapp:1.0
```

#### Способ 2: Загрузка готового образа (`image load`)

Если образ уже собран на хост-машине (или скачан), его можно напрямую загрузить в кэш Minikube:

```bash
# Прямая загрузка образа в Minikube
minikube image load myapp:1.0

# Проверка, что образ доступен в кластере
minikube image ls
# → docker.io/library/myapp:1.0
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
