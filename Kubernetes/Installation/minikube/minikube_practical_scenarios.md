# Minikube: практические сценарии

## Определения

**Minikube** — основной инструмент для локального запуска и управления однонодовым или многонодовым кластером **Kubernetes (K8s)**. Он автоматизирует создание среды (VM или контейнер) и первичную инициализацию компонентов Control Plane.

Подробные определения и описание архитектуры см. в **[Minikube: определения и концепции](./minikube_concepts.md)**.

---

## Базовые концепции

### Предварительные требования

Перед началом работы убедитесь, что система соответствует актуальным требованиям (на август 2026):

- **Аппаратные ресурсы:** минимум 2 ядра CPU и 4 ГБ RAM (рекомендуется 8 ГБ+). Подробнее см. в **[minikube_concepts.md](./minikube_concepts.md)**.
- **Драйвер:** на Linux и macOS рекомендуется использовать Docker.
- **Docker:** должен быть установлен из официальных репозиториев (не snap). См. **[Установка Docker на Ubuntu](../../../Docker/docker_install_ubuntu.md)**.

---

## Практические сценарии

### Установка Minikube

| ОС | Команда установки |
| :--- | :--- |
| **macOS (Homebrew)** | `brew install minikube` |
| **Linux (Binary)** | `curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && sudo install minikube-linux-amd64 /usr/local/bin/minikube` |
| **Windows (Chocolatey)** | `choco install minikube` |

**Проверка установки:** `minikube version`

---

### Запуск и базовая настройка

#### Запуск с параметрами по умолчанию
```bash
minikube start
```
При первом запуске Minikube автоматически выберет лучший доступный драйвер (обычно Docker) и скачает образ актуальной версии Kubernetes.

#### Настройка ресурсов и версии
Для специфических задач рекомендуется явно указывать ресурсы:
```bash
minikube start \
  --cpus=4 \
  --memory=8192mb \
  --disk-size=50g \
  --kubernetes-version=v1.36.0 \
  --container-runtime=containerd
```

#### Постоянная конфигурация
Чтобы не вводить параметры каждый раз, используйте `minikube config`:
```bash
# Установка драйвера по умолчанию
minikube config set driver docker

# Установка лимитов ресурсов
minikube config set cpus 4
minikube config set memory 8192
```

---

### Управление профилями (Profiles)

Профили позволяют запускать несколько изолированных кластеров.

```bash
# Запуск кластера для проекта "alpha"
minikube start -p alpha --nodes=2

# Переключение между профилями (изменение контекста kubectl)
minikube profile alpha

# Список всех профилей и их статус
minikube profile list
```

---

### Работа с сетью

#### Доступ к сервисам типа NodePort
```bash
# Экспонирование приложения
kubectl expose deployment my-app --type=NodePort --port=80

# Получение URL для доступа с хоста
minikube service my-app --url
```

#### Использование LoadBalancer (minikube tunnel)
Поскольку в локальной среде нет облачного балансировщика, внешний IP останется в состоянии `<pending>`. Для назначения IP запустите:
```bash
# Команда должна работать в отдельном терминале
minikube tunnel
```
После запуска туннеля `EXTERNAL-IP` в `kubectl get svc` сменится с `pending` на реальный IP (обычно `127.0.0.1` или IP из сети Docker).

#### Настройка Ingress
1.  Включите аддон: `minikube addons enable ingress`.
2.  Добавьте запись в `/etc/hosts`:
    ```text
    # IP можно узнать через minikube ip
    192.168.49.2  my-app.local
    ```
3.  Создайте ресурс Ingress, указывающий на ваш сервис.

---

### Работа с образами и файлами

#### Использование локальных образов (без Push)
Самый эффективный способ разработки — использование демона Minikube:
```bash
# Настройка текущей сессии терминала
eval $(minikube docker-env)

# Теперь docker build соберет образ сразу ВНУТРИ Minikube
docker build -t local-image:latest .

# В манифесте пода укажите imagePullPolicy: Never
```

#### Копирование файлов в контейнер
```bash
# Копирование файла в узел Minikube
minikube cp ./config.yaml /home/docker/config.yaml

# Копирование из узла на хост
minikube cp minikube:/var/log/syslog ./local_syslog.log
```

#### Монтирование директорий (Mount)
Для работы с большими объемами данных или кодом в реальном времени:
```bash
minikube mount /Users/user/project:/data/project
```
> **Внимание:** Процесс `mount` должен быть активен (не закрывайте терминал).

---

### Аддоны и расширения

| Задача | Команда |
| :--- | :--- |
| **Список всех аддонов** | `minikube addons list` |
| **Мониторинг ресурсов** | `minikube addons enable metrics-server` |
| **Веб-интерфейс** | `minikube dashboard` |
| **Локальный реестр** | `minikube addons enable registry` |
| **Service Mesh** | `minikube addons enable istio` |

---

### Многонодовые конфигурации (Multi-node)

Для тестирования планирования (scheduling) и отказоустойчивости:
```bash
# Запуск с 3 узлами
minikube start --nodes=3

# Добавление узла в работающий кластер
minikube node add --worker

# Удаление конкретного узла
minikube node remove minikube-m02
```

---

### Обслуживание и отладка

#### Остановка и удаление
```bash
# Остановка (состояние сохраняется)
minikube stop

# Полное удаление (все данные и тома будут стерты)
minikube delete --all --purge
```

#### Диагностика
- **Статус компонентов:** `minikube status`.
- **Логи запуска:** `minikube logs`.
- **Вход в консоль узла:** `minikube ssh`.
- **Проверка встроенного kubectl:** `minikube kubectl -- get pods`.

---

### Типичные ошибки и решения

| Проблема | Решение |
| :--- | :--- |
| **The "docker" driver should not be used with root privileges** | Не запускайте `minikube start` через `sudo`. Используйте обычного пользователя, состоящего в группе `docker`. |
| **Exiting due to GUEST_MISSING_CONN_TRACK** | Необходима установка `conntrack` на хосте (актуально для драйвера `none`). |
| **ImagePullBackOff** | Проверьте `imagePullPolicy`. Если используете `docker-env`, установите `Never`. |
| **Tunnels not working on macOS** | Убедитесь, что у `minikube tunnel` есть права администратора (запросит пароль). |
| **Insufficient memory** | Minikube требует минимум 2ГБ для K8s, но для аддонов (Istio, Ingress) нужно 8ГБ+. |

---

## Дополнительная информация

### См. также
- **[Minikube: определения и концепции](./minikube_concepts.md)** — архитектура, драйверы и теория.
- **[kubectl: установка](../kubectl_installation.md)** — подготовка основного инструмента управления.
- **[Docker: установка на Ubuntu](../../../Docker/docker_install_ubuntu.md)** — настройка среды исполнения.

### Полезные ссылки
- **Примеры манифестов:** [GitHub minikube/examples](https://github.com/kubernetes/minikube/tree/master/examples)
- **Troubleshooting guide:** [Official Docs](https://minikube.sigs.k8s.io/docs/handbook/debugging/)
