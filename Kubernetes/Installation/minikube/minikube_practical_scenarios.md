# Minikube: Практические сценарии

## Определения

**Minikube** — инструмент для запуска локального однонодового кластера Kubernetes. Используется для разработки, тестирования и обучения.

> **Связанные концепции:** [Определения и архитектура Minikube](./minikube_concepts.md)

---

## Базовые концепции

### Требования

| Компонент | Версия | Назначение |
| :--- | :--- | :--- |
| **Docker** | 18.03+ | Container runtime (обязательно) |
| **Minikube** | Последняя | Инструмент развёртывания |
| **kubectl** | Любая | Управление кластером (опционально, встроен в Minikube) |
| **CPU** | 2 ядра | Минимум, рекомендовано 4 |
| **Память** | 2 ГБ | Минимум, рекомендовано 4–8 ГБ |
| **Диск** | 20 ГБ | Минимум, рекомендовано 40 ГБ |

> **Примечание:** Подробная информация о драйверах, kubeconfig и архитектуре — в [minikube_concepts.md](./minikube_concepts.md).

### Поддерживаемые версии Kubernetes

Minikube поддерживает последнюю версию Kubernetes + 6 предыдущих минорных версий.

| Версия Kubernetes | Статус | EOL (End of Life) |
| :--- | :--- | :--- |
| 1.33 | Активная поддержка | Апрель 2027 |
| 1.32 | Активная поддержка | Декабрь 2026 |
| 1.31 | Активная поддержка | Август 2026 |

> **Примечание:** Версии 1.30 и ниже достигли EOL. Проверяйте [release notes](https://github.com/kubernetes/minikube/releases) для актуальных образов.

---

## Практические сценарии

### Установка Docker Engine (Linux — Ubuntu/Debian)

> **Важно:** Minikube не работает со **snap-пакетом** Docker на Debian и производных. Используйте **deb-пакеты** из официального репозитория.

**1. Обновление репозиториев и установка зависимостей:**

```bash
sudo apt update && sudo apt install -y ca-certificates curl gnupg
```

**2. Добавление GPG-ключа и репозитория Docker:**

```bash
# Создание директории для ключей
sudo install -m 0755 -d /etc/apt/keyrings

# Скачивание официального GPG-ключа Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Добавление репозитория Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

**3. Установка Docker Engine:**

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**4. Добавление пользователя в группу docker (без sudo):**

```bash
sudo usermod -aG docker $USER
newgrp docker
```

> **Важно:** Без добавления в группу `docker` Minikube не сможет запустить контейнеры с нужными привилегиями.

**5. Проверка статуса Docker:**

```bash
systemctl status docker
# → Active: active (running)
```

> **Ресурсы ВМ:** Для стабильной работы Minikube рекомендуется виртуальная машина с **4 ГБ RAM** минимум. При 2 ГБ возможны ошибки при запуске кластера.

### Установка Minikube

| ОС | Команда |
| :--- | :--- |
| **macOS (Homebrew)** | `brew install minikube` |
| **Linux (binary)** | `curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && sudo install minikube-linux-amd64 /usr/local/bin/minikube` |
| **Windows (Chocolatey)** | `choco install minikube` |

**Проверка:** `minikube version`

### Установка kubectl (опционально)

Minikube включает встроенную версию kubectl. Для установки отдельной версии:

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

**Что происходит:** автоматический выбор драйвера, проверка драйвера, скачивание образа узла, создание контейнера/VM, инициализация Kubernetes (включая storage-provisioner и default-storageclass для имитации PV/PVC), настройка kubeconfig.

**Результат:** кластер запущен, kubectl настроен на использование контекста `minikube`.

> **Примечание:** Флаг `--driver=docker` необязателен — Minikube автоматически определяет доступный драйвер. Подробнее о драйверах — в [minikube_concepts.md](./minikube_concepts.md).

#### Запуск с драйвером none (bare metal)

```bash
minikube start --driver=none
```

**Требования:**

- Только Linux
- Docker установлен как deb-пакет (не snap)
- Запуск от root или пользователя с привилегиями

> **Внимание:** Драйвер `none` устанавливает компоненты Kubernetes на хост-систему. Это может конфликтовать с другими сервисами и не рекомендуется для продакшн. Подробнее — в [minikube_concepts.md](./minikube_concepts.md).

#### Запуск с параметрами

| Параметр | Команда |
| :--- | :--- |
| **Выделение ресурсов** | `minikube start --cpus=4 --memory=8192mb` |
| **Версия Kubernetes** | `minikube start --kubernetes-version=v1.33.0` |
| **Драйвер** | `minikube start --driver=virtualbox` |
| **Сеть (insecure registry)** | `minikube start --insecure-registry="10.0.0.0/24"` |

### Проверка состояния

| Проверка | Команда |
| :--- | :--- |
| **Статус кластера** | `minikube status` |
| **Узлы** | `minikube kubectl -- get nodes` или `kubectl get nodes` |
| **Namespaces** | `minikube kubectl -- get namespaces` |

**Ожидаемый вывод для узлов:**

```
NAME       STATUS   ROLES           AGE   VERSION
minikube   Ready    control-plane   2m    v1.33.0
```

---

### Работа с кластером

#### Развёртывание приложений

```bash
# Создание deployment
kubectl create deployment nginx --image=nginx:1.27

# Проверка подов
kubectl get pods

# Создание сервиса
kubectl expose deployment nginx --port=80 --type=NodePort

# Получение URL сервиса
minikube service nginx --url
```

#### Доступ к Dashboard

```bash
minikube dashboard
```

Открывает Kubernetes Dashboard в браузере.

#### SSH-доступ к узлу

```bash
minikube ssh
```

**Внутри узла:**

```bash
# Проверка компонентов
kubectl get pods -n kube-system

# Логи kubelet
journalctl -u kubelet
```

#### Копирование файлов

```bash
# В кластер
minikube cp ./config.yaml /home/docker/config.yaml

# Из кластера
minikube cp /var/log/pods/mypod.log ./logs/
```

---

### Управление кластером

| Операция | Команда |
| :--- | :--- |
| **Остановка (сохранение данных)** | `minikube stop` |
| **Запуск** | `minikube start` |
| **Перезапуск** | `minikube restart` |
| **Удаление текущего кластера** | `minikube delete` |
| **Удаление конкретного кластера** | `minikube delete -p cluster-name` |
| **Удаление всех кластеров** | `minikube delete --all` |

---

### Работа с аддонами

> **Полный список аддонов и их назначение** — в [minikube_concepts.md](./minikube_concepts.md).

#### Просмотр списка аддонов

```bash
minikube addons list
```

**Пример вывода:**

```
|         ADDON NAME          | PROFILE  |    STATUS    |
|-----------------------------|----------|--------------|
| dashboard                   | minikube | enabled      |
| default-storageclass        | minikube | enabled      |
| ingress                     | minikube | disabled     |
| metrics-server              | minikube | disabled     |
| registry                    | minikube | disabled     |
| storage-provisioner         | minikube | enabled      |
```

#### Включение аддонов

```bash
# Ingress-контроллер
minikube addons enable ingress

# Metrics-server
minikube addons enable metrics-server

# Локальный Docker Registry
minikube addons enable registry
```

#### Настройка Ingress

```bash
# Включение аддона
minikube addons enable ingress

# Проверка подов ingress-nginx
kubectl get pods -n ingress-nginx

# Применение Ingress-ресурса
kubectl apply -f ingress.yaml
```

---

### Работа с образами Docker

#### Сборка образов внутри Minikube

```bash
# Переключение на Docker-демон Minikube
eval $(minikube docker-env)

# Сборка образа
docker build -t myapp:1.0 .

# Развёртывание из локального образа
kubectl create deployment myapp --image=myapp:1.0
```

#### Использование локального Registry

```bash
# Включение registry-аддона
minikube addons enable registry

# Тегирование и отправка образа
docker tag myapp:1.0 localhost:5000/myapp:1.0
docker push localhost:5000/myapp:1.0

# Развёртывание из registry
kubectl create deployment myapp --image=localhost:5000/myapp:1.0
```

---

### Multi-node кластеры

#### Создание multi-node кластера

```bash
minikube start --nodes=3 --cpus=2 --memory=4096mb
kubectl get nodes
```

**Ожидаемый вывод:**

```
NAME           STATUS   ROLES           AGE   VERSION
minikube       Ready    control-plane   5m    v1.33.0
minikube-m02   Ready    <none>          4m    v1.33.0
minikube-m03   Ready    <none>          3m    v1.33.0
```

| Операция | Команда |
| :--- | :--- |
| **Добавление узла** | `minikube node add --worker` |
| **Удаление узла** | `minikube node remove minikube-m03` |

---

### Отладка и мониторинг

#### Просмотр логов

```bash
# Все поды в namespace по метке
kubectl logs -n kube-system -l app=coredns

# Конкретный под
kubectl logs <pod-name> -n <namespace>
```

#### Описание ресурсов

```bash
# Информация об узле
kubectl describe node minikube

# Информация о поде
kubectl describe pod <pod-name>
```

#### Метрики ресурсов

```bash
# Включение metrics-server
minikube addons enable metrics-server

# Метрики узлов и подов
kubectl top nodes
kubectl top pods
```

---

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `docker system info` не работает | Docker не запущен | Запустить Docker Desktop |
| `Unable to connect to the server` | Кластер остановлен | `minikube start` |
| `context "minikube" does not exist` | kubeconfig повреждён | `minikube start` (пересоздаст) |
| Под в статусе `Pending` | Нет ресурсов | `minikube stop && minikube start --cpus=4 --memory=8192mb` |
| `ImagePullBackOff` | Образ недоступен | Проверить имя образа, использовать `eval $(minikube docker-env)` |

---

## Дополнительная информация

### Рекомендации по поиску инструкций

Официальная документация Minikube не всегда содержит полные пошаговые инструкции для конкретных ОС. Рекомендуется использовать детализированные поисковые запросы:

- **Пример:** `install minikube ubuntu 22.04` вместо общей страницы установки
- Кастомные инструкции часто включают важные нюансы (добавление пользователя в группу docker, работа с репозиториями), отсутствующие в официальной документации

---

### Смотрите также

- **Официальная документация:** [minikube.sigs.k8s.io](https://minikube.sigs.k8s.io/docs/)
- **GitHub:** [kubernetes/minikube](https://github.com/kubernetes/minikube)
- **Определения и концепции:** [minikube_concepts.md](./minikube_concepts.md)
