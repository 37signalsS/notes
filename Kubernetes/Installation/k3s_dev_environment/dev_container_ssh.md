# Создание Dev-контейнера с SSH

Руководство по созданию изолированного рабочего пространства внутри кластера K3s. Контейнер предоставляет доступ по протоколу SSH и персистентную домашнюю директорию, используется для удаленной разработки непосредственно в кластере.

Контекст: Часть серии по созданию dev-окружения в K3s. Развертывание через Helm описано в [Развертывание Dev-контейнера с помощью Helm](./dev_container_helm_deployment.md). Предварительно требуется [вспомогательный образ kubeutils](./kubeutils_image.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Dev-контейнер** | Изолированное рабочее пространство в кластере Kubernetes с настроенным SSH-сервером, оптимизированное для работы с удаленными IDE (VS Code, JetBrains Gateway). |
| **Init Script** | Скрипт инициализации (`ENTRYPOINT`), выполняющий финальную настройку среды при старте: создание пользователя, синхронизацию UID/GID и запуск демона `sshd`. |
| **SSH Certificate Authority (CA)** | Метод аутентификации, при котором сервер доверяет ключам, подписанным доверенным центром сертификации. Это исключает необходимость управления файлами `authorized_keys` на каждом узле. |
| **Pod Security Standards (PSS)** | Политики безопасности Kubernetes (Privileged, Baseline, Restricted). SSH-контейнеры обычно требуют режима `Baseline` или специальных исключений для запуска демона. |
| **NodePort** | Тип Service в Kubernetes, выделяющий статичный порт на каждом узле кластера (диапазон 30000-32767). Используется для доступа к SSH-серверу без Ingress Controller. |
| **SecurityContext** | Конфигурация безопасности Pod/контейнера: `runAsUser`, `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation`, `seccompProfile`. Определяет уровень привилегий процесса. |
| **readinessProbe** | Механизм проверки готовности контейнера принимать трафик. Для SSH используется `tcpSocket` на порту 22 — если TCP-соединение устанавливается, под считается готовым. |
| **ServiceAccount** | Объект Kubernetes, предоставляющий поду идентификатор для аутентификации перед API-сервером. Используется для доступа пода к ресурсам кластера (Secrets, ConfigMap). |
| **hostPath** | Тип тома Kubernetes, монтирующий директорию с файловой системы хост-узла в под. Используется для персистентности данных, но привязывает под к конкретному узлу. |
| **Local Path Provisioner** | Встроенный в K3s провизионер для динамического создания томов типа `hostPath` с автоматическим управлением поддиректориями. Альтернатива ручному созданию директорий. |
| **Containerfile** | Файл конфигурации контейнерного образа, совместимый с Docker и Podman. Идентичен по синтаксису Dockerfile, но является частью стандартов OCI. |

Навигация по SSH: [Обзор SSH](../../../Linux/Security/ssh/ssh_overview.md) | [Настройка сервера](../../../Linux/Security/ssh/server/ssh_server_security_overview.md) | [Управление сессиями](../../../Linux/Security/ssh/ssh_session_management.md)

---

## Основные концепции

### Архитектура решения

Dev-контейнер представляет собой образ на базе Ubuntu 24.04 LTS с SSH-сервером и набором базовых утилит.

Компоненты:
1.  **Базовый образ:** `ubuntu:24.04` — LTS-версия (Noble Numbat), обеспечивающая долгосрочную поддержку и актуальность системных библиотек.
2.  **SSH-сервер:** OpenSSH 9.6p1+ — настроен на работу по протоколу v2 с отключением парольной аутентификации.
3.  **Персистентность:** Домашняя директория разработчика монтируется через `hostPath` или `Local PV`, сохраняя настройки IDE, кэши инструментов и историю команд.
4.  **Скрипт инициализации:** Связывает жизненный цикл пода с UID/GID хостовой системы для бесшовной работы с томами.

Принцип работы:
```text
┌─────────────────────────────────────────────────────────┐
│                    Pod: dev-container                   │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────┐      ┌──────────────────────────┐  │
│  │ init-container.sh ──→  │ sshd (foreground)        │  │
│  │ (синхронизация) │      │ рабочая среда bash       │  │
│  └─────────────────┘      └──────────────────────────┘  │
│                            │                            │
│                            ↓                            │
│                   ┌─────────────────┐                   │
│                   │ hostPath Volume │ ←── K3s Node      │
│                   │ /home/<user>    │     filesystem    │
│                   └─────────────────┘                   │
└─────────────────────────────────────────────────────────┘
                              │
                              ↓ SSH (NodePort / Ingress TCP)
                    ┌─────────────────┐
                    │  Developer IDE  │
                    │  (VS Code SSH)  │
                    └─────────────────┘
```

### Сравнение подходов к среде разработки

| Аспект | Традиционная ВМ | Dev-контейнер в K3s |
| :--- | :--- | :--- |
| **Изоляция** | Общая среда на команду, риск конфликтов. | Строгая контейнерная изоляция на уровне Pod. |
| **Воспроизводимость** | Зависит от состояния ВМ (Configuration Drift). | Гарантируется иммутабельным Docker-образом. |
| **Масштабирование** | Трудоемкое изменение ресурсов (RAM/CPU). | Мгновенное управление квотами через K8s. |
| **Безопасность** | Компрометация ВМ дает доступ ко всей системе. | Ограничена namespace'ом и ServiceAccount. |
| **Скорость запуска** | Минуты (загрузка ОС). | Секунды (старт контейнера). |

### Механика Init-скрипта

Скрипт решает критическую проблему монтирования томов в Kubernetes: несовпадение прав. Если `hostPath` на узле принадлежит UID 1000, а пользователь в образе имеет UID 1001, возникнет ошибка `Permission denied`.

Логика `init-container.sh`:
1.  **Чтение параметров:** Получение желаемых UID/GID из переменных среды (`DEV_USER_ID`, `DEV_GROUP_ID`).
2.  **Создание пользователя:** Динамическое создание системной группы и пользователя с точным совпадением ID.
3.  **Настройка sudo:** Выдача пользователю прав `sudo` без пароля (критично для установки инструментов "на лету").
4.  **Корректировка прав:** Идемпотентное выполнение `chown` для домашней директории, если она была смонтирована с другими правами.
5.  **Запуск демона:** Запуск `sshd` в режиме PID 1 с выводом логов в `stderr` для диагностики через `kubectl logs`.

### Сетевая доступность SSH

SSH-сервер в контейнере доступен извне через три основных механизма:

| Механизм | Способ暴露 | Порт | Рекомендация |
| :--- | :--- | :--- | :--- |
| **NodePort** | `<NodeIP>:<NodePort>` | 30000-32767 | Простая настройка, для dev-окружений |
| **Ingress TCP** | `<Domain>:22` через Ingress Controller | 22 | Требует TCP-проброса в NGINX Ingress |
| **port-forward** | `kubectl port-forward` | Локальный | Временный доступ, для отладки |

**NodePort** — рекомендуемый способ для dev-среды. Сервис типа `NodePort` выделяет порт на диапазоне 30000-32767 и пробрасывает трафик на порт 22 контейнера.

**Ingress TCP** — для Ingress Controller (NGINX) необходимо включить TCP-проброс через ConfigMap с маппингом портов. Это позволяет подключаться по SSH через доменное имя (например, `ssh.dev.local:22`).

**port-forward** — временный способ доступа для отладки. Не требует создания Service, но работает только при запущенном `kubectl port-forward`.

### Жизненный цикл контейнера

```text
Build Image → Push to Registry → Create PVC (home dir) → Deploy Pod →
Init Container (UID sync) → Main Container (sshd) → Readiness Probe (TCP:22) →
Service (NodePort) → SSH Connection from IDE
```

Каждый этап критичен:
- **Build Image:** Финальная точка, где добавляются зависимости и настраивается безопасность.
- **Push to Registry:** Публикация в Harbor/GitLab Registry для доступа из кластера.
- **Create PVC:** Создание персистентного хранилища для данных разработчика.
- **Deploy Pod:** Развертывание через Deployment или Helm-чарт.
- **Init Container:** Синхронизация UID/GID, настройка SSH-ключей.
- **Main Container:** Запуск `sshd` в foreground-режиме.
- **Readiness Probe:** Проверка готовности SSH-сервера принимать подключения.
- **Service:** Экспонирование SSH-порта через NodePort/LoadBalancer.
- **SSH Connection:** Подключение IDE к контейнеру.

---

## Требования и предварительная подготовка

### Программные зависимости

| Компонент | Минимальная версия | Рекомендация | Назначение |
| :--- | :--- | :--- | :--- |
| **K3s** | v1.28+ | v1.36.3+k3s1 | Оркестратор Kubernetes |
| **Docker / Podman** | 24.0+ | 27.x | Сборка образа локально |
| **Helm** | 3.12+ | v4.2.3 | Управление чартами |
| **kubectl** | Совпадает с версией K3s | v1.36.3 | Управление ресурсами кластера |
| **SSH-клиент** | OpenSSH 8.0+ | OpenSSH 9.8+ | Подключение к контейнеру |

### Предварительные шаги

1. **K3s установлен и работает:**
```bash
kubectl get nodes
# → NAME     STATUS   ROLES                  AGE   VERSION
# → server   Ready    control-plane,master   2m    v1.36.3+k3s1
```

2. **Ingress Controller установлен** (NGINX рекомендуется):
```bash
kubectl -n ingress-nginx get pods
# → NAME                                        READY   STATUS    AGE
# → ingress-nginx-controller-xxx                1/1     Running   5m
```

3. **Репозиторий образов доступен** (Harbor или GitLab Registry):
```bash
# Проверка доступа к реестру
docker login harbor.dev.local
# → Login Succeeded
```

4. **Директория для хранения данных создана** (или используется Local Path Provisioner):
```bash
# На хосте K3s
sudo mkdir -p /mnt/data/homes
sudo chmod 755 /mnt/data/homes
```

---

## Практические сценарии

### Шаг 1: Dockerfile для Dev-контейнера (Ubuntu 24.04)

Файл оптимизирован для безопасности и включает исправления для OpenSSH в Ubuntu.

```dockerfile
FROM ubuntu:24.04

# Отключение интерактивных запросов apt
ENV DEBIAN_FRONTEND=noninteractive

# Установка SSH-сервера и базовых утилит
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    git \
    curl \
    ca-certificates \
    vim \
    bash-completion \
    && rm -rf /var/lib/apt/lists/*

# Директория для privilege separation (критично для Ubuntu/Debian)
RUN mkdir -p /run/sshd && chmod 0755 /run/sshd

# Усиление безопасности конфигурации sshd
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config && \
    # Ограничение времени на логин для защиты от regreSSHion
    echo "LoginGraceTime 30" >> /etc/ssh/sshd_config

# Копирование и настройка скрипта инициализации
COPY init-container.sh /usr/local/bin/init-container.sh
RUN chmod +x /usr/local/bin/init-container.sh

EXPOSE 22

ENTRYPOINT ["/usr/local/bin/init-container.sh"]
```

### Шаг 2: Скрипт инициализации (`init-container.sh`)

Обеспечивает корректную работу с UID/GID и системными сертификатами.

```bash
#!/bin/bash
set -e

# Переменные окружения с дефолтными значениями
USER_NAME=${DEV_USER_NAME:-developer}
GROUP_NAME=${DEV_GROUP_NAME:-developer}
USER_ID=${DEV_USER_ID:-1000}
GROUP_ID=${DEV_GROUP_ID:-1000}

# Создание группы (если она еще не существует)
if ! getent group "${GROUP_NAME}" > /dev/null 2>&1; then
    groupadd -g "${GROUP_ID}" "${GROUP_NAME}"
fi

# Создание пользователя
if ! id -u "${USER_NAME}" > /dev/null 2>&1; then
    useradd -u "${USER_ID}" -g "${GROUP_ID}" -s /bin/bash -m "${USER_NAME}"
    passwd -d "${USER_NAME}" # Отключение пароля
fi

# Настройка sudo без пароля
echo "${USER_NAME} ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/${USER_NAME}"
chmod 0440 "/etc/sudoers.d/${USER_NAME}"

# Идемпотентная смена владельца домашней директории
chown "${USER_ID}:${GROUP_ID}" "/home/${USER_NAME}"

# Импорт дополнительных CA-сертификатов (например, корпоративный Harbor)
CA_CERT_PATH="/etc/ssl/certs/custom-ca.crt"
if [ -f "$CA_CERT_PATH" ]; then
    cp "$CA_CERT_PATH" /usr/local/share/ca-certificates/
    update-ca-certificates > /dev/null 2>&1
fi

# Запуск SSH-демона
# -D: не отсоединяться (foreground)
# -e: вывод логов в stderr (доступно через kubectl logs)
echo "Starting sshd for ${USER_NAME} (UID: ${USER_ID})..."
exec /usr/sbin/sshd -D -e
```

### Шаг 3: Локальное тестирование образа

Проверка работоспособности перед развертыванием в K3s.

```bash
# 1. Сборка
docker build -t dev-container:2026 .

# 2. Подготовка локального тома
mkdir -p ~/dev-home/.ssh
cp ~/.ssh/id_ed25519.pub ~/dev-home/.ssh/authorized_keys
chmod 700 ~/dev-home/.ssh && chmod 600 ~/dev-home/.ssh/authorized_keys

# 3. Запуск контейнера
docker run -d \
  -p 2222:22 \
  -e DEV_USER_NAME=$USER \
  -e DEV_USER_ID=$(id -u) \
  -e DEV_GROUP_ID=$(id -g) \
  -v ~/dev-home:/home/$USER \
  --name dev-debug \
  dev-container:2026

# 4. Проверка подключения
ssh -p 2222 $USER@localhost
# → Welcome to Ubuntu 24.04.1 LTS (GNU/Linux 6.x)
```

### Шаг 4: Публикация образа в реестр

```bash
# Тегирование
docker tag dev-container:2026 harbor.dev.local/library/dev-container:2026

# Пуш в Harbor
docker push harbor.dev.local/library/dev-container:2026
# → The push refers to repository [harbor.dev.local/library/dev-container]
# → 2026: digest: sha256:abc123... size: 1362
```

### Шаг 5: Развертывание в K3s через kubectl

```bash
# Создание namespace
kubectl create namespace dev-workspaces

# Создание Secret с SSH-ключами
kubectl create secret generic dev-ssh-keys \
  --namespace dev-workspaces \
  --from-file=authorized_keys=$HOME/.ssh/id_ed25519.pub

# Создание Deployment
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dev-container
  namespace: dev-workspaces
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dev-container
  template:
    metadata:
      labels:
        app: dev-container
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      initContainers:
        - name: init-ssh
          image: ubuntu:24.04
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -e
              mkdir -p /home/developer/.ssh
              chmod 700 /home/developer/.ssh
              cat /etc/ssh-keys/authorized_keys > /home/developer/.ssh/authorized_keys
              chmod 600 /home/developer/.ssh/authorized_keys
              chown -R 1000:1000 /home/developer/.ssh
          volumeMounts:
            - name: home-dir
              mountPath: /home/developer
            - name: ssh-keys
              mountPath: /etc/ssh-keys
              readOnly: true
      containers:
        - name: dev-container
          image: harbor.dev.local/library/dev-container:2026
          ports:
            - containerPort: 22
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2000m"
              memory: "4Gi"
          readinessProbe:
            tcpSocket:
              port: 22
            initialDelaySeconds: 5
            periodSeconds: 10
          env:
            - name: DEV_USER_NAME
              value: "developer"
            - name: DEV_USER_ID
              value: "1000"
            - name: DEV_GROUP_ID
              value: "1000"
          volumeMounts:
            - name: home-dir
              mountPath: /home/developer
            - name: ca-certs
              mountPath: /etc/ssl/certs/custom-ca.crt
              subPath: custom-ca.crt
              readOnly: true
      volumes:
        - name: home-dir
          hostPath:
            path: "/mnt/data/homes/developer"
            type: DirectoryOrCreate
        - name: ssh-keys
          secret:
            secretName: dev-ssh-keys
        - name: ca-certs
          configMap:
            name: dev-container-ca
EOF

# Создание сервиса NodePort
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: dev-container-ssh
  namespace: dev-workspaces
spec:
  type: NodePort
  selector:
    app: dev-container
  ports:
    - name: ssh
      port: 22
      targetPort: 22
      nodePort: 32022
      protocol: TCP
EOF
```

### Шаг 6: Проверка развертывания

```bash
# Статус подов
kubectl -n dev-workspaces get pods
# → NAME                            READY   STATUS    AGE
# → dev-container-xxx               1/1     Running   30s

# Статус сервиса
kubectl -n dev-workspaces get svc dev-container-ssh
# → NAME                TYPE       CLUSTER-IP     EXTERNAL-IP   PORT(S)         AGE
# → dev-container-ssh   NodePort   10.43.x.x      <none>        22:32022/TCP   30s

# Получение IP узла
kubectl get nodes -o wide
# → NAME     STATUS   ROLES                  AGE   VERSION        INTERNAL-IP
# → server   Ready    control-plane,master   10m   v1.36.3+k3s1   192.168.1.100
```

### Шаг 7: Подключение через SSH

```bash
# Подключение к контейнеру
ssh -p 32022 developer@192.168.1.100
# → Welcome to Ubuntu 24.04.1 LTS (GNU/Linux 6.x)

# Проверка окружения
whoami
# → developer

id
# → uid=1000(developer) gid=1000(developer) groups=1000(developer)

# Проверка персистентности
echo "test" > ~/test-file.txt
# (при перезапуске пода файл сохранится)
```

### Шаг 8: Подключение IDE (VS Code Remote SSH)

1. Установите расширение **Remote - SSH** в VS Code.
2. Добавьте конфигурацию в `~/.ssh/config`:
```
Host dev-container
    HostName 192.168.1.100
    Port 32022
    User developer
    IdentityFile ~/.ssh/id_ed25519
```
3. Подключитесь через палитру команд (`Ctrl+Shift+P` -> `Remote-SSH: Connect to Host`).
4. Выберите `dev-container` и дождитесь установки VS Code Server в контейнере.

### Шаг 9: Подключение IDE (JetBrains Gateway)

1. Установите **JetBrains Gateway** и нужный IDE (IntelliJ, GoLand и т.д.).
2. Выберите **SSH** в качестве способа подключения.
3. Укажите: `Host: 192.168.1.100`, `Port: 32022`, `User: developer`.
4. JetBrains автоматически скопируетnecessary файлы в контейнер и запустит backend-сервер IDE.

---

## Типичные ошибки и устранение неполадок

### Ошибка: `Permission denied (publickey)`

**Причина:** SSH-ключ не добавлен в `authorized_keys`, неверные права доступа или несовпадение UID.

```bash
# Диагностика на хосте
ls -la ~/dev-home/.ssh/
# → drwx------ developer developer authorized_keys (должно быть 700)
# → -rw------- developer developer authorized_keys (должно быть 600)

# Проверка содержимого authorized_keys
cat ~/dev-home/.ssh/authorized_keys
# → ssh-ed25519 AAAAC3... (должен содержать ваш публичный ключ)

# Проверка UID/GID на хосте и в контейнере
id developer
# → uid=1000(developer) gid=1000(developer)

# Исправление прав (на хосте)
sudo chown -R 1000:1000 ~/dev-home
chmod 700 ~/dev-home/.ssh
chmod 600 ~/dev-home/.ssh/authorized_keys
```

### Ошибка: `Connection refused`

**Причина:** SSH-сервер не запущен или под не прошел readinessProbe.

```bash
# Проверка статуса пода
kubectl -n dev-workspaces get pods
# → dev-container-xxx   CrashLoopBackOff   (или Error)

# Просмотр логов
kubectl -n dev-workspaces logs deploy/dev-container --previous
# → Starting sshd for developer (UID: 1000)... (если есть, значит запуск был)
# → Permissions 0777 for '/home/developer/.ssh' are too open. (проблема с правами)

# Проверка readinessProbe
kubectl -n dev-workspaces describe pod dev-container-xxx | grep -A 5 "Readiness"
# → tcpSocket: (1000) port 22 timeout: 1s
```

### Ошибка: `Broken pipe` при подключении

**Причина:** Под разорвался из-за тайм-аута или проблем с сетью.

```bash
# Проверка сетевой связности
nc -zv 192.168.1.100 32022
# → Connection to 192.168.1.100 port 32022 [tcp/*] succeeded!

# Увеличение тайм-аутов в ~/.ssh/config
Host dev-container
    ServerAliveInterval 60
    ServerAliveCountMax 3
    TCPKeepAlive yes
```

### Ошибка: `No space left on device`

**Причина:** Диск на хосте заполнен или PVC достиг лимита.

```bash
# Проверка диска на хосте
df -h /mnt/data
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       50G   48G   2G   96% /

# Проверка использования в контейнере
kubectl -n dev-workspaces exec deploy/dev-container -- df -h /home/developer
# → /dev/sda1       50G   48G   2G   96% /home/developer
```

### Ошибка: `Readiness probe failed`

**Причина:** SSH-сервер не отвечает на TCP-подключение.

```bash
# Проверка listening-портов в контейнере
kubectl -n dev-workspaces exec deploy/dev-container -- ss -tlnp
# → LISTEN  0  128  0.0.0.0:22  0.0.0.0:*  users:(("sshd",pid=1,fd=3))

# Проверка логов sshd
kubectl -n dev-workspaces logs deploy/dev-container | grep sshd
# → Server listening on 0.0.0.0 port 22.
# → Server listening on :: port 22.
```

---

## Мониторинг и наблюдаемость

### Проверка здоровья контейнера

```bash
# Статус пода и последнее событие
kubectl -n dev-workspaces get pods -o wide
# → NAME                            READY   STATUS    RESTARTS   AGE
# → dev-container-xxx               1/1     Running   0          30m

# Детальная информация
kubectl -n dev-workspaces describe pod dev-container-xxx
# → Conditions:
# →   Type              Status
# →   Initialized       True
# →   Ready             True
# →   ContainersReady   True
# →   PodScheduled      True

# Проверка потребления ресурсов
kubectl -n dev-workspaces top pod dev-container-xxx
# → NAME                            CPU(cores)   MEMORY(bytes)
# → dev-container-xxx               15m          128Mi
```

### Сбор логов

```bash
# Логи основного контейнера (sshd выводит в stderr)
kubectl -n dev-workspaces logs deploy/dev-container -f
# → Starting sshd for developer (UID: 1000)...
# → Connection from 192.168.1.1 port 54321
# → Accepted publickey for developer from 192.168.1.1 port 54321 ssh2

# Логи init-контейнера
kubectl -n dev-workspaces logs deploy/dev-container -c init-ssh
# → + getent group developer
# → + groupadd -g 1000 developer

# Логи за определенный период
kubectl -n dev-workspaces logs deploy/dev-container --since=1h
```

### Мониторинг сетевой активности

```bash
# Проверка активных SSH-сессий в контейнере
kubectl -n dev-workspaces exec deploy/dev-container -- who
# → developer pts/0 2026-08-30 10:15 (192.168.1.1)

# Проверка открытых портов
kubectl -n dev-workspaces exec deploy/dev-container -- ss -tlnp
# → LISTEN  0  128  0.0.0.0:22  0.0.0.0:*  users:(("sshd",pid=1,fd=3))

# Проверка количества подключений
kubectl -n dev-workspaces exec deploy/dev-container -- ss -s
# → Total: 5
# → TCP:   3 (estab 1, closed 0, orphaned 0, timewait 0)
```

---

## Безопасность

### Рекомендации по харденингу

| Параметр | Рекомендация | Реализация |
| :--- | :--- | :--- |
| **Run as non-root** | Запрет запуска от root | `runAsNonRoot: true`, `runAsUser: 1000` |
| **Read-only FS** | Только чтение для системных директорий | `readOnlyRootFilesystem: true` (кроме /home) |
| **No privilege escalation** | Запрет повышения привилегий | `allowPrivilegeEscalation: false` |
| **Seccomp profile** | Ограничение системных вызовов | `seccompProfile: { type: RuntimeDefault }` |
| **Resource limits** | Ограничение CPU/RAM | `resources.limits: { cpu: "2", memory: "4Gi" }` |

### SecurityContext для Pod

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
containers:
  - name: dev-container
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: false  # sshd требует запись в /run/sshd
      capabilities:
        drop:
          - ALL
```

### Настройка RBAC для ServiceAccount

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: dev-container-role
  namespace: dev-workspaces
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
    resourceNames: ["dev-ssh-keys"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dev-container-binding
  namespace: dev-workspaces
subjects:
  - kind: ServiceAccount
    name: dev-container-sa
    namespace: dev-workspaces
roleRef:
  kind: Role
  name: dev-container-role
  apiGroup: rbac.authorization.k8s.io
```

### Сетевая безопасность (NetworkPolicy)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: dev-container-netpol
  namespace: dev-workspaces
spec:
  podSelector:
    matchLabels:
      app: dev-container
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - ipBlock:
            cidr: 192.168.1.0/24  # Только доверенная сеть
      ports:
        - protocol: TCP
          port: 22
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 443  # HTTPS (обновления)
        - protocol: TCP
          port: 53  # DNS
        - protocol: UDP
          port: 53  # DNS
```

### Защита SSH-ключей

1. **Используйте Ed25519:** `ssh-keygen -t ed25519` — более быстрый и безопасный алгоритм.
2. **Храните ключи в Secret:** Не храните публичные ключи в ConfigMap — используйте Kubernetes Secret.
3. **Ротация ключей:** Регулярно обновляйте `authorized_keys` через Helm-параметры.
4. **FIDO2 токены:** Для критической инфраструктуры используйте аппаратные ключи (`ed25519-sk`).

---

## Дополнительная информация

### Команды управления контейнером

```bash
# Перезапуск пода
kubectl -n dev-workspaces rollout restart deployment dev-container

# Масштабирование (для multi-developer среды)
kubectl -n dev-workspaces scale deployment dev-container --replicas=3

# Обновление образа
kubectl -n dev-workspaces set image deployment/dev-container \
  dev-container=harbor.dev.local/library/dev-container:2027

# Откат на предыдущую версию
kubectl -n dev-workspaces rollout undo deployment dev-container

# Проверка истории ревизий
kubectl -n dev-workspaces rollout history deployment dev-container
```

### Структура директорий

| Путь | Назначение |
| :--- | :--- |
| `/home/<user>/` | Домашняя директория разработчика (персистентная) |
| `/home/<user>/.ssh/` | SSH-ключи доступа |
| `/home/<user>/.ssh/authorized_keys` | Публичные ключи для аутентификации |
| `/home/<user>/.bashrc` | Конфигурация оболочки (персистентная) |
| `/home/<user>/.gitconfig` | Настройки Git (персистентные) |
| `/run/sshd/` | Временные файлы sshd (теряются при рестарте) |
| `/etc/ssh/sshd_config` | Конфигурация SSH-сервера (в образе) |

### Актуальность компонентов (август 2026)

| Компонент | Версия | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **Ubuntu** | 24.04.2 LTS | LTS | Поддержка до 2029 |
| **OpenSSH** | 9.6p1 | Stable | Встроен в Ubuntu 24.04 |
| **K3s** | v1.36.3+k3s1 | Stable | Релиз от 5 августа 2026 |
| **Helm** | v4.2.3 | Stable | Мажорная версия v4 |
| **kubectl** | v1.36.3 | Stable | Должен совпадать с версией K3s |

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **hostPath** | Побег на узел через монтирование | Ограничивайте монтирование только папкой проекта |
| **SSH от root** | Компрометация контейнера | Запуск от имени `runAsUser: 1000` |
| **sudo NOPASSWD** | Неограниченные права в контейнере | Используйте квоты ресурсов (Resource Quotas) |
| **Статические ключи** | Утрата контроля при утечере | Регулярная ротация или переход на SSH CA |
| **NodePort** | Доступ из любой сети | NetworkPolicy + VPN для ограничения доступа |
| **Персистентность** | Потеря данных при удалении PVC | Регулярный бэкап через Velero |

### См. также

- **Развертывание:** [Helm-чарт для Dev-контейнера](./dev_container_helm_deployment.md) -- декларативное управление
- **Инфраструктура:** [Архитектура K3s](./k3s_architecture.md) -- обзор всей лаборатории
- **SSH:** [Обзор SSH](../../../Linux/Security/ssh/ssh_overview.md) -- протокол и архитектура
