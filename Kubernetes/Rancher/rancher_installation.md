# Установка Rancher Server

## Определения

**Rancher Server** — центральный управляющий компонент платформы Rancher (Management Plane). Он обеспечивает оркестрацию множества кластеров Kubernetes, управление пользователями (RBAC), политиками безопасности и интеграцию с внешними системами аутентификации.

**Management Cluster** (Локальный кластер) — Kubernetes-кластер, в который устанавливается сам Rancher Server. Крайне не рекомендуется запускать пользовательские нагрузки в этом кластере для обеспечения стабильности панели управления.

**cert-manager** — контроллер Kubernetes для автоматизации выпуска и обновления TLS-сертификатов. Является критическим пререквизитом для установки Rancher при использовании автоматической генерации сертификатов.

## Базовые концепции

### Выбор базовой инфраструктуры (2026)

Для развертывания Management-кластера в современных инсталляциях (Rancher v2.10+) рекомендуется использовать специализированные дистрибутивы SUSE:

| Параметр | **RKE2** (Рекомендовано для Prod) | **K3s** (Для Edge/Dev/Test) |
| :--- | :--- | :--- |
| **Безопасность** | Hardened по умолчанию (FIPS, CIS) | Требует ручного ужесточения |
| **Ресурсы** | Высокое потребление (8GB+ RAM) | Минимальное (4GB+ RAM) |
| **Ingress** | NGINX (в комплекте) | Traefik (в комплекте) |
| **Назначение** | Корпоративные ЦОД, высокие требования к ИБ | Удаленные офисы, Edge-устройства, малые инсталляции |

### Методы установки

1.  **Высокая доступность (HA) через Helm**: установка в подготовленный кластер (RKE2, K3s, EKS) из 3-х узлов. Единственный метод, рекомендуемый для производственных сред.
2.  **Docker-инсталляция**: запуск одной командой `docker run`. Только для быстрого ознакомления. Данные хранятся внутри контейнера; миграция в HA-кластер затруднена.

## Практические сценарии

### Подготовка Management-кластера (RKE2)

Перед установкой Rancher необходимо развернуть Kubernetes. Пример базовой настройки узла RKE2:

```bash
# /etc/rancher/rke2/config.yaml
token: "my-shared-secret"
tls-san:
  - "rancher.example.com"
```

### Установка cert-manager (Пререквизит)

Rancher требует TLS для всех соединений. Если вы не используете собственные сертификаты (BYO), установка `cert-manager` обязательна:

```bash
# 1. Добавление репозитория Jetstack
helm repo add jetstack https://charts.jetstack.io
helm repo update

# 2. Установка (с автоматическим созданием CRD)
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true
```

### Развертывание Rancher Server через Helm

После того как кластер и `cert-manager` готовы, приступайте к установке Rancher:

```bash
# 1. Репозиторий
helm repo add rancher-latest https://releases.rancher.com/server-charts/latest
helm repo update

# 2. Namespace
kubectl create namespace cattle-system

# 3. Инсталляция
helm upgrade --install rancher rancher-latest/rancher \
  --namespace cattle-system \
  --set hostname=rancher.example.com \
  --set bootstrapPassword=admin \
  --set ingress.tls.source=rancher \
  --set replicaCount=3
```

**Разбор ключевых параметров:**
*   `hostname`: FQDN (Full Qualified Domain Name), по которому будет доступен UI. Должен быть заранее направлен на IP-адрес Load Balancer или Ingress узлов.
*   `ingress.tls.source=rancher`: Rancher попросит `cert-manager` выпустить самоподписанный сертификат.
*   `replicaCount=3`: обеспечивает доступность панели управления при выходе из строя одного узла.

## Особенности эксплуатации

### Проверка статуса установки

После запуска Helm-чарта отслеживайте состояние Rollout:
```bash
kubectl -n cattle-system rollout status deploy/rancher
```

### Безопасность и PSA (Pod Security Admission)

В актуальных версиях Kubernetes политики PSP удалены. Rancher автоматически настраивает необходимые метки для Namespace, но при ручном создании Namespace для приложений рекомендуется использовать стандартные профили:
```bash
kubectl label namespace my-app pod-security.kubernetes.io/enforce=baseline
```

### Удаление и очистка

Для полной очистки узла от Rancher и управляющих агентов используйте скрипты удаления, поставляемые с дистрибутивом:

```bash
# Удаление RKE2
/usr/local/bin/rke2-uninstall.sh

# Очистка системного агента Rancher (на управляемых узлах)
/usr/local/bin/rancher-system-agent-uninstall.sh
```

## Дополнительная информация

### Рекомендации по железу

*   **Диски**: Всегда используйте SSD/NVMe. `etcd` крайне чувствителен к задержкам записи (latency).
*   **Сеть**: Обеспечьте синхронизацию времени через NTP. Разница более чем в 1 секунду между узлами приведет к сбою проверки TLS-сертификатов.

**Связанные темы:**

* [Rancher: Обзор платформы](./rancher_overview.md) — архитектура и возможности.
* [Kubernetes: Секреты](../Base/secrets/creating_secrets.md) — управление учетными данными.
* [Ingress: Контроллер NGINX](../../Networking/Ingress/nginx_controller.md) — настройка точки входа.
