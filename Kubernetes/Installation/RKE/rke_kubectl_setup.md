# RKE: Установка kubectl и настройка доступа

> [!WARNING]
> **RKE1 достиг конца жизненного цикла (EOL) 31 июля 2025 года.** 
> Поддержка прекращена, основное внимание Rancher Labs полностью переключено на **RKE2**. Эксплуатация допускается только для существующих сред с обязательным планом миграции.

## Определения

**kubectl** — стандартный интерфейс командной строки (CLI) для взаимодействия с API-сервером Kubernetes. Позволяет создавать, просматривать, изменять и удалять ресурсы внутри кластера. Версия `kubectl` должна отличаться от версии кластера не более чем на одну минорную версию (правило ±1).

**kubeconfig** — YAML-файл (обычно `~/.kube/config`), содержащий данные для аутентификации на одном или нескольких кластерах. RKE автоматически генерирует этот файл при завершении установки и сохраняет его как `kube_config_cluster.yml` в текущей директории.

**Контекст (Context)** — логическая связка внутри kubeconfig, объединяющая три элемента:
1. **Cluster:** куда подключаться (URL API-сервера, CA-сертификат).
2. **User:** с какими учетными данными подключаться (клиентские сертификаты, токены).
3. **Namespace (опционально):** пространство имен по умолчанию для этого контекста.

**kube_config_cluster.yml** — файл конфигурации доступа, создаваемый утилитой RKE CLI в текущей директории после выполнения команды `rke up`. Содержит полную конфигурацию для подключения к кластеру, включая адрес API-сервера и сертификаты аутентификации.

**cluster.rkestate** — критически важный файл состояния кластера. Содержит полную копию конфигурации, данные сертификатов и текущее состояние ресурсов. Без этого файла ротация сертификатов и обновление кластера через RKE CLI невозможны.

## Базовые концепции

### Взаимодействие с RKE

Для полноценного управления кластером RKE необходимо обеспечить связку между локальной машиной администратора и API-сервером кластера (порт 6443). Основные этапы:

1. **Установка клиента:** Наличие бинарного файла `kubectl`, версия которого должна отличаться от версии кластера не более чем на одну минорную версию (правило ±1).
2. **Получение данных доступа:** Извлечение сертификатов и адресов из Rancher UI или из локальных файлов после работы RKE CLI.
3. **Изоляция конфигурации:** Настройка прав доступа к файлам конфигов для предотвращения кражи токенов и ключей.

### Структура kubeconfig для RKE

После выполнения `rke up` файл `kube_config_cluster.yml` содержит следующую структуру:

```yaml
apiVersion: v1
kind: Config
clusters:
- cluster:
    # CA-сертификат кластера (Base64)
    certificate-authority-data: LS0tLS1...
    # Адрес API-сервера RKE кластера
    server: https://192.168.1.100:6443
  name: production-cluster

users:
- name: admin
  user:
    # Клиентский сертификат администратора (Base64)
    client-certificate-data: LS0tLS...
    # Приватный ключ администратора (Base64)
    client-key-data: LS0tLS...

contexts:
- context:
    cluster: production-cluster
    user: admin
    # Пространство имен по умолчанию
    namespace: default
  name: production-admin

# Текущий активный контекст
current-context: production-admin
```

**Ключевые поля для RKE:**
- `certificate-authority-data` — корневой сертификат CA кластера, используемый для проверки подлинности API-сервера.
- `server` — URL API-сервера (стандартный порт 6443).
- `client-certificate-data` — сертификат клиента для аутентификации на API-сервере.
- `client-key-data` — приватный ключ клиента.

> [!IMPORTANT]
> Файл `kube_config_cluster.yml` содержит критически важные секреты (приватные ключи). Никогда не храните его в git-репозиториях и всегда устанавливайте права доступа `chmod 600`.

### Совместимость версий

RKE требует, чтобы версия `kubectl` на локальной машине совпадала с версией Kubernetes в кластере (с допуском ±1 минорная версия):

```bash
# Проверка версии клиента
kubectl version --client --short
# → Client Version: v1.28.10

# Проверка версии сервера (после настройки доступа)
kubectl version --short
# → Server Version: v1.28.10

# Проверка только серверной версии (без подключения)
kubectl version -o json | jq -r '.serverVersion.gitVersion'
```

> [!WARNING]
> Использование `kubectl` с большой разницей версий (например, клиент 1.20 против сервера 1.30) может приводить к ошибкам совместимости и непредсказуемому поведению. Обновляйте клиент при каждом обновлении кластера.

## Практические сценарии

### Шаг 1: Установка kubectl

#### Вариант А: Через официальный репозиторий (рекомендуется)

```bash
# Для Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y apt-transport-https
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update && sudo apt-get install -y kubectl

# Для RHEL/CentOS
cat <<EOF | sudo tee /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/v1.28/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/v1.28/rpm/repodata/repomd.xml.key
EOF
sudo yum install -y kubectl

# Для macOS (Homebrew)
brew install kubectl@1.28
```

#### Вариант Б: Прямое скачивание бинарника

```bash
# Для Linux
curl -LO "https://dl.k8s.io/release/v1.28.10/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# Для macOS (Intel)
curl -LO "https://dl.k8s.io/release/v1.28.10/bin/darwin/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# Для macOS (Apple Silicon)
curl -LO "https://dl.k8s.io/release/v1.28.10/bin/darwin/arm64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
```

#### Вариант В: Проверка установки

```bash
kubectl version --client
# → Client Version: version.Info{Major:"1", Minor:"28", GitVersion:"v1.28.10", ...}

kubectl version --client --short
# → Client Version: v1.28.10
```

### Шаг 2: Получение конфигурации

#### Метод А: Через RKE CLI (Автономный кластер)

После успешного выполнения команды `rke up`, в той же директории создается файл `kube_config_cluster.yml`. Это ваш основной административный доступ.

```bash
# Проверка наличия файла
ls -la kube_config_cluster.yml cluster.rkestate
# -rw------- 1 user user 2543 Aug 31 12:00 kube_config_cluster.yml
# -rw------- 1 user user 8921 Aug 31 12:00 cluster.rkestate

# Просмотр содержимого файла (маскированные секреты)
kubectl --kubeconfig kube_config_cluster.yml config view

# Просмотр полного файла (включая ключи!)
kubectl --kubeconfig kube_config_cluster.yml config view --raw

# Использование файла напрямую без перемещения в ~/.kube
kubectl --kubeconfig kube_config_cluster.yml get nodes

# Краткая проверка кластера
kubectl --kubeconfig kube_config_cluster.yml cluster-info
```

#### Метод Б: Через Rancher UI (Управляемый кластер)

Если кластер импортирован или создан через Rancher:
1. Перейдите в **Cluster Management** → **Clusters**.
2. Выберите ваш кластер.
3. Нажмите кнопку **Kubeconfig File** в верхней части панели.
4. Скопируйте содержимое или скачайте файл.
5. Сохраните его как `~/.kube/config` или используйте через флаг `--kubeconfig`.

#### Метод В: Через копирование с мастер-узла

Если RKE CLI недоступен, скопируйте конфигурацию с мастер-узла:

```bash
# Подключение к мастер-узлу по SSH
ssh user@master-ip

# Копирование конфигурации
sudo cp /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Или без перемещения в ~/.kube
kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes
```

### Шаг 3: Настройка локального окружения

#### Базовая настройка

```bash
# Создание структуры директорий
mkdir -p $HOME/.kube

# Если у вас еще нет основного конфига:
cp kube_config_cluster.yml $HOME/.kube/config

# Установка жестких прав доступа (обязательно!)
chmod 600 $HOME/.kube/config

# Проверка прав
ls -la $HOME/.kube/config
# -rw------- 1 user user 2543 Aug 31 12:00 /home/user/.kube/config
```

#### Управление несколькими кластерами

Если вы работаете с несколькими кластерами одновременно:

```bash
# Сохранение конфигураций отдельных кластеров
cp kube_config_cluster.yml ~/.kube/prod-cluster.yaml
cp kube_config_cluster.yml ~/.kube/dev-cluster.yaml

# Экспорт переменной окружения с несколькими путями
# (разделитель - двоеточие в Linux/macOS)
export KUBECONFIG=~/.kube/config:~/.kube/prod-cluster.yaml:~/.kube/dev-cluster.yaml

# Просмотр всех доступных контекстов
kubectl config get-contexts

# Переключение между контекстами
kubectl config use-context production-admin
kubectl config use-context dev-admin

# Объединение в один постоянный файл
kubectl config view --flatten > ~/.kube/config_merged
mv ~/.kube/config_merged ~/.kube/config
unset KUBECONFIG
```

#### Использование переменных окружения для временного доступа

```bash
# Временная переменная для текущей сессии
export KUBECONFIG=$(pwd)/kube_config_cluster.yml

# Или для конкретной команды
KUBECONFIG=$(pwd)/kube_config_cluster.yml kubectl get nodes

# Сброс после использования
unset KUBECONFIG
```

### Шаг 4: Проверка связи и совместимости

```bash
# Проверка базовой работоспособности кластера
kubectl cluster-info
# → Kubernetes control plane is running at https://192.168.1.100:6443
# → CoreDNS is running at https://192.168.1.100:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

# Просмотр узлов кластера
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                      AGE   VERSION   INTERNAL-IP     ...
# → node-01    Ready    controlplane,etcd,worker   10d   v1.28.10  192.168.1.10   ...
# → node-02    Ready    worker                     10d   v1.28.10  192.168.1.11   ...

# Просмотр системных подов
kubectl get pods -n kube-system
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → coredns-7ff77c879f-xxxxx                   1/1     Running   0          10d
# → ingress-nginx-controller-xxxxx              1/1     Running   0          10d
# → kube-apiserver-node-01                      1/1     Running   0          10d
# → kube-controller-manager-node-01             1/1     Running   0          10d
# → kube-proxy-xxxxx                            1/1     Running   0          10d
# → kube-scheduler-node-01                      1/1     Running   0          10d
# → metrics-server-xxxxx                        1/1     Running   0          10d

# Проверка версии сервера и клиента
kubectl version --short
# → Client Version: v1.28.10
# → Server Version: v1.28.10

# Проверка версии API
kubectl api-versions | head -5
# → admissionregistration.k8s.io/v1
# → apiextensions.k8s.io/v1
# → apiregistration.k8s.io/v1

# Проверка доступных ресурсов
kubectl api-resources --verbs=list --namespaced -o name | head -10
# → configmaps
# → endpoints
# → persistentvolumeclaims
# → pods
# → secrets
# → serviceaccounts
# → services
```

## Дополнительная информация

### Восстановление kubeconfig при потере

Если файл `kube_config_cluster.yml` утерян или поврежден:

**Вариант 1: Восстановление из cluster.rkestate**

```bash
# Проверка наличия файла состояния
ls -la cluster.rkestate

# Если файл существует, его можно восстановить через RKE CLI
# (требуется доступ к мастер-узлам по SSH)
rke up --config cluster.yml

# RKE обнаружит, что кластер уже существует, и обновит только конфигурацию
# После этого файл kube_config_cluster.yml будет восстановлен
```

**Вариант 2: Копирование с мастер-узла**

```bash
# Если master-узел доступен по SSH
ssh user@master-ip "cat /etc/kubernetes/admin.conf" > kube_config_cluster.yml

# Или напрямую с мастер-узла
ssh user@master-ip "sudo cat /etc/kubernetes/admin.conf" | kubectl --kubeconfig=- config view
```

**Вариант 3: Ручное создание (если есть доступ к кластеру)**

```bash
# Если у вас есть другой kubeconfig с доступом к кластеру
# или кластер доступен изнутри (in-cluster config)

# Создание нового ServiceAccount для доступа
kubectl create serviceaccount admin-recovery -n kube-system

# Создание ClusterRoleBinding
kubectl create clusterrolebinding admin-recovery-binding \
  --clusterrole=cluster-admin \
  --serviceaccount=kube-system:admin-recovery

# Получение токена (для Kubernetes 1.24+)
kubectl create token admin-recovery -n kube-system --duration=24h

# Формирование kubeconfig вручную
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CA=$(kubectl get secret -n kube-system -o jsonpath='{.items[?(@.metadata.annotations.kubernetes\.io/service-account\.name=="admin-recovery")].data.ca\.crt}')
TOKEN=$(kubectl create token admin-recovery -n kube-system --duration=24h)

cat <<EOF > kube_config_cluster.yml
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${CA}
    server: ${SERVER}
  name: recovery-cluster
contexts:
- context:
    cluster: recovery-cluster
    user: admin-recovery
    namespace: default
  name: recovery-admin
current-context: recovery-admin
users:
- name: admin-recovery
  user:
    token: ${TOKEN}
EOF
```

### Диагностика проблем доступа

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **`Unable to connect to the server: x509: certificate has expired`** | Истек сертификат API-сервера или клиентский сертификат | Выполните ротацию сертификатов: `rke cert rotate --config cluster.yml`. Проверьте даты сертификатов: `openssl x509 -in /etc/kubernetes/ssl/kube-apiserver.crt -noout -dates` |
| **`error: unable to connect to the server: Connection refused`** | API-сервер недоступен или неверный IP/порт | Проверьте доступность порта 6443: `nc -zv <api-server-ip> 6443`. Убедитесь, что API-сервер запущен: `docker ps \| grep kube-apiserver` |
| **`error: You must be logged in to the server (Unauthorized)`** | kubeconfig устарел или был перегенерирован | Скопируйте актуальный `kube_config_cluster.yml` с мастер-узла или выполните `rke up` для обновления |
| **`error: the server doesn't have a resource type "nodes"`** | Несоответствие версий или поврежденный kubeconfig | Проверьте версию: `kubectl version`. Переустановите kubectl или получите новый kubeconfig |
| **`certificate signed by unknown authority`** | CA-сертификат в kubeconfig не соответствует серверному | Скопируйте актуальный `kube_config_cluster.yml` или получите новый CA с мастер-узла |
| **`connection timed out`** | Сетевые проблемы или файрвол блокирует порт 6443 | Проверьте маршрутизацию: `traceroute <api-server-ip>`. Проверьте файрвол: `iptables -L -n \| grep 6443` |
| **`KUBECONFIG not set`** | Переменная окружения не установлена | Установите: `export KUBECONFIG=~/.kube/config` или используйте флаг `--kubeconfig` |

### Рекомендации по безопасности

#### Хранение и защита kubeconfig

```bash
# Установка прав доступа (обязательно!)
chmod 600 $HOME/.kube/config

# Проверка прав
ls -la $HOME/.kube/config
# -rw------- 1 user user 2543 Aug 31 12:00 /home/user/.kube/config

# Если файл находится в общедоступной директории
chown $(id -u):$(id -g) $HOME/.kube/config
chmod 600 $HOME/.kube/config
```

#### Изоляция сред (Development/Production)

```bash
# Раздельные файлы для разных окружений
cp prod-cluster.yaml ~/.kube/prod.yaml
cp dev-cluster.yaml ~/.kube/dev.yaml

# Использование отдельных контекстов
export KUBECONFIG=~/.kube/prod.yaml
kubectl config current-context
# → production-admin

export KUBECONFIG=~/.kube/dev.yaml
kubectl config current-context
# → dev-admin

# Избегайте использования KUBECONFIG с несколькими путями в продакшн-среде
# (риск случайного применения манифестов не в тот кластер)
```

#### Проверка контекста перед деструктивными командами

```bash
# Всегда проверяйте текущий контекст перед удалением/изменением ресурсов
kubectl config current-context
# → production-admin

# Просмотр всех доступных контекстов
kubectl config get-contexts
# → CURRENT   NAME                CLUSTER             AUTHINFO            NAMESPACE
# → *         production-admin    production-cluster   admin               default
# →           dev-admin           dev-cluster          admin               default

# Переключение на нужный контекст
kubectl config use-context dev-admin
```

#### Удаление устаревших контекстов

```bash
# Очистка неиспользуемых контекстов
kubectl config delete-context stale-context-1
kubectl config delete-context stale-context-2

# Удаление неиспользуемых пользователей
kubectl config delete-user old-user

# Удаление неиспользуемых кластеров
kubectl config delete-cluster old-cluster

# Очистка кэша OIDC-плагина (если используется)
kubelogin token cache --cleanup
```

### Интеграция с CI/CD

Для автоматизации deployments через CI/CD системы (GitLab CI, GitHub Actions, Jenkins):

```bash
# 1. Создание ServiceAccount для CI/CD
kubectl create serviceaccount cicd-deployer -n kube-system

# 2. Назначение ограниченных прав (RBAC)
kubectl create rolebinding cicd-deployer-binding \
  --clusterrole=edit \
  --serviceaccount=kube-system:cicd-deployer \
  -n kube-system

# 3. Получение токена (для Kubernetes 1.24+)
TOKEN=$(kubectl create token cicd-deployer -n kube-system --duration=8760h)

# 4. Формирование kubeconfig
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CA=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

cat <<EOF > cicd-kubeconfig.yaml
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${CA}
    server: ${SERVER}
  name: production-cluster
contexts:
- context:
    cluster: production-cluster
    user: cicd-deployer
    namespace: default
  name: cicd-context
current-context: cicd-context
users:
- name: cicd-deployer
  user:
    token: ${TOKEN}
EOF
```

### Удаление и очистка

При полном удалении кластера RKE:

```bash
# Удаление кластера (остановит и удалит все контейнеры на узлах)
rke remove --config cluster.yml

# После удаления кластера удалите локальные файлы конфигурации
rm -f kube_config_cluster.yml cluster.rkestate

# Удаление kubeconfig из ~/.kube (если был скопирован)
rm -f $HOME/.kube/config

# Очистка переменной окружения
unset KUBECONFIG
```

---

**См. также:**
* [RKE: Основные концепции](./rke_concepts.md)
* [RKE: Управление и поиск неисправностей](./rke_management_scenarios.md)
* [Kubeconfig: Подключение к кластеру Kubernetes](../../Operations/kubeconfig_and_connection.md)
