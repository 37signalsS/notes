# RKE (Rancher Kubernetes Engine)

## Определения

**RKE (Rancher Kubernetes Engine)** — дистрибутив Kubernetes от Rancher Labs для развертывания production-кластеров на bare-metal и виртуальных машинах. Поддерживает декларативную конфигурацию через YAML и управление через Rancher UI или CLI.

**Rancher** — платформа управления Kubernetes, предоставляющая веб-интерфейс для развертывания, мониторинга и управления кластерами (включая RKE, RKE2, K3s).

**kubeconfig** — YAML-файл конфигурации доступа к Kubernetes API (контексты, пользователи, кластеры). Расположен в `~/.kube/config`.

> **Примечание:** RKE2 (Rancher Government Kubernetes) — следующая версия RKE с улучшенной безопасностью (FIPS-совместимость, hardened компоненты). Не путать с RKE1.

## Базовые концепции

### Отличия RKE от kubeadm

| Аспект | kubeadm | RKE |
| :--- | :--- | :--- |
| **Установка** | Команды `kubeadm init/join` на узлах | Через `cluster.yml` + `rke up` |
| **Конфигурация** | Ручная на каждом узле | Декларативная (YAML) |
| **Управление** | kubectl + kubeadm | Rancher UI + kubectl |
| **kubectl на узлах** | Устанавливается автоматически | Не устанавливается (только через Rancher) |
| **HA** | Ручная настройка | Встроенная поддержка |

### Архитектура доступа

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│   kubectl   │ ───► │  kubeconfig  │ ───► │  RKE API Server │
│  (локально) │      │ (~/.kube/)   │      │   (порт 6443)   │
└─────────────┘      └──────────────┘      └─────────────────┘
                                                    │
                                  ┌─────────────────┼─────────────────┐
                                  │                 │                 │
                         ┌────────▼───────┐ ┌──────▼──────┐ ┌───────▼──────┐
                         │  Control Plane │ │ Worker Node │ │ Worker Node  │
                         │    (etcd+API)  │ │             │ │              │
                         └────────────────┘ └─────────────┘ └──────────────┘
```

### Типы дистрибутивов Rancher

* **RKE2** — современный дистрибутив с улучшенной безопасностью (FIPS, hardened компоненты). Подходит для production-сред с высокими требованиями к безопасности.
* **K3s** — легковесный дистрибутив для edge, IoT и тестовых сред. Минимальное потребление ресурсов.

### Сетевые плагины

* **Flannel** — простой оверлейный CNI-плагин. Минимальная конфигурация, подходит для базовых сценариев.
* **Calico** — мощный CNI с поддержкой `NetworkPolicy`. Рекомендован для production-сред.
* **Cilium** — высокопроизводительный CNI на базе eBPF с расширенными функциями безопасности и обсервабилити.

### Особенности узлов RKE-кластера

* **Taints на системных узлах** — узлы с ролями `etcd` и `Control Plane` имеют taints (например, `node-role.kubernetes.io/control-plane:NoSchedule`), предотвращающие размещение обычных подов.
* **Встроенный Ingress Controller** — RKE-кластеры поставляются с Nginx Ingress Controller (DaemonSet на Worker-узлах).
* **Автоматическое обновление сертификатов** — ротация TLS-сертификатов через Rancher UI (`Cluster Management` → `Rotate Certificates`).

## Практические сценарии

### Методы управления RKE

| Метод | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Rancher UI** | Визуальный интерфейс, мониторинг, упрощенное развертывание | Требует ресурсов на Rancher Server |
| **kubectl** | Стандартный инструмент, скрипты, CI/CD-интеграция | Только CLI, нет визуализации |
| **RKE CLI** | Полная автоматизация, infrastructure as code | Меньше возможностей чем UI |
| **Terraform RKE provider** | Infrastructure as Code, версионирование | Сложнее настройка |

### Установка kubectl и получение kubeconfig

**Установка kubectl:**

```bash
# Linux
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
kubectl version --client
```

**Получение kubeconfig из Rancher UI:**

1. Открыть Rancher UI (`https://rancher.your-domain.com`)
2. Выбрать кластер в `Cluster Management` или `Dashboard`
3. Нажать кнопку `Kubeconfig File` (верхний правый угол)
4. Сохранить содержимое в `~/.kube/config`
5. Проверить доступ: `kubectl get nodes`

**Работа с несколькими контекстами:**

```bash
# Просмотр контекстов
kubectl config get-contexts

# Переключение контекста
kubectl config use-context c-m-xxxxxxxxx

# Слияние конфигураций
export KUBECONFIG=~/.kube/config:~/.kube/rke-config
```

### Развертывание кластера через Rancher UI

1. Перейти в `Global` → `Clusters` → `Add Cluster`
2. Выбрать `Create a new Kubernetes cluster using Rancher Kubernetes Engine`
3. Настроить кластер:
   * Имя и описание
   * Версия Kubernetes и тип дистрибутива (RKE2/K3s)
   * Network Provider (Flannel/Calico/Cilium)
   * Cloud Provider (`None` для bare-metal)
4. Добавить узлы с ролями:
   * **etcd** — 3 или 5 узлов для кворума
   * **Control Plane** — 2 или 3 узла для HA
   * **Worker** — рабочие узлы для подов приложений
5. Запустить `rancher-agent` на каждом узле (команда из Rancher UI)
6. Дождаться статуса `Active`

### Troubleshooting

**Certificate expired:**

```bash
# Проверка
kubectl get nodes
# Ошибка: x509: certificate has expired or is not yet valid

# Решение: Cluster Management → ⋮ → Rotate Certificates
```

**Connection refused:**

```bash
# Проверка доступности API
curl -k https://<rke-api-ip>:6443/healthz
telnet <rke-api-ip> 6443
```

**Unauthorized:**

```bash
# Проверка токена
kubectl config view --raw -o jsonpath='{.users[0].user.token}'

# Перегенерация: Users & Authentication → API Keys → Create Key
```

## Дополнительная информация

### Безопасность

* Хранение kubeconfig: `chmod 600 ~/.kube/config`
* Использовать ServiceAccount с минимальными правами
* Избегать использования `admin.conf` в production
* Ротация сертификатов: автоматическая (1 год) или через Rancher UI

### Интеграция с CI/CD

**GitLab CI:**

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  variables:
    KUBE_CONFIG: $RKE_KUBECONFIG  # Base64 encoded
  script:
    - echo $KUBE_CONFIG | base64 -d > /tmp/kubeconfig
    - export KUBECONFIG=/tmp/kubeconfig
    - kubectl apply -f k8s/
```

**GitHub Actions:**

```yaml
- name: Set up kubeconfig
  run: |
    mkdir -p ~/.kube
    echo "${{ secrets.RKE_KUBECONFIG }}" | base64 -d > ~/.kube/config
    chmod 600 ~/.kube/config

- name: Deploy to RKE
  run: kubectl apply -f k8s/
```

### RKE CLI (альтернатива Rancher UI)

**Установка:**

```bash
curl -L https://github.com/rancher/rke/releases/download/v1.6.0/rke_linux-amd64 -o rke
chmod +x rke
sudo mv rke /usr/local/bin/
```

**Развертывание через cluster.yml:**

```yaml
nodes:
  - address: 192.168.1.10
    user: root
    role: [controlplane, worker, etcd]
  - address: 192.168.1.11
    user: root
    role: [worker]

services:
  etcd:
    snapshot: true
    creation: 6h
    retention: 24h

ssh_key_path: ~/.ssh/id_rsa
```

```bash
rke up --config cluster.yml
export KUBECONFIG=$(pwd)/kube_config_cluster.yml
```

---

**См. также:** [kubeadm: Быстрый старт](../kubeadm/index.md) — альтернативный метод установки Kubernetes, [kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md) — детали конфигурации доступа, [RKE2 документация](https://docs.rke2.io/) — следующая версия RKE.
