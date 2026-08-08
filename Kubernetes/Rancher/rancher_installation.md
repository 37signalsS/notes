# Установка Rancher Server

## Определения

**Rancher Server** — центральный компонент управления (Management Plane), обеспечивающий оркестрацию мультикластерных сред, управление безопасностью и автоматизацию жизненного цикла Kubernetes.

**Management Cluster (Local)** — выделенный кластер Kubernetes (рекомендуется RKE2), предназначенный исключительно для работы Rancher Server. 
*   **Правило эксплуатации:** запрещено запускать бизнес-нагрузки в Local-кластере для предотвращения деградации производительности панели управления.

**Bootstrap Password** — временный пароль администратора, задаваемый при первой установке. В современных версиях (v2.10+) рекомендуется передавать его через секреты Kubernetes или параметры Helm для соблюдения стандартов безопасности (Secret Management).

**cert-manager** — инструмент автоматизации PKI в Kubernetes. Для Rancher v2.13+ рекомендуется версия **v1.20+** с поддержкой Gateway API.

## Базовые концепции

### Выбор базовой инфраструктуры (2026)

Для Management-кластера в высоконагруженных средах (100+ управляемых кластеров) рекомендуется следующая конфигурация:

| Параметр | **RKE2** (Standard) | **K3s** (Edge/Small) |
| :--- | :--- | :--- |
| **Среда выполнения** | `containerd` | `containerd` |
| **Безопасность** | FIPS-совместимость, CIS Hardening | Профиль `hardened` (опционально) |
| **База данных** | `etcd` (обязательно SSD/NVMe) | `etcd` или `PostgreSQL` |
| **Ingress** | NGINX (Default) | Traefik / Gateway API |

### Архитектура высокой доступности (HA)

Единственный поддерживаемый метод для Production — установка в HA-кластер из **3-х Master-узлов**. Это обеспечивает отказоустойчивость `etcd` (кворум) и самого API Rancher.

## Практические сценарии

### Шаг 1: Подготовка узлов и RKE2

Минимальные требования: 4 CPU, 8 GB RAM (рекомендуется 16 GB).

```bash
# /etc/rancher/rke2/config.yaml
token: "secure-bootstrap-token"
tls-san:
  - "rancher.example.com"
cni: canal # Стандарт для RKE2
```

### Шаг 2: Установка cert-manager (v1.20+)

В 2026 году cert-manager требует явного включения поддержки Gateway API, если планируется его использование:

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true \
  --set config.enableGatewayAPI=true
```

### Шаг 3: Установка Rancher Server через Helm

Для установки используйте канал `latest` (или `stable` для максимальной консервативности):

```bash
# Добавление репозитория
helm repo add rancher-latest https://releases.rancher.com/server-charts/latest

# Установка
helm upgrade --install rancher rancher-latest/rancher \
  --namespace cattle-system \
  --create-namespace \
  --set hostname=rancher.example.com \
  --set bootstrapPassword=admin \
  --set ingress.tls.source=rancher \
  --set replicaCount=3 \
  --set global.cattle.psp.enabled=false # PSP удалены в K8s 1.25+
```

### Использование собственного CA (Private CA)

Если организация использует внутренний удостоверяющий центр:
1.  Установите `ingress.tls.source=secret`.
2.  Создайте TLS-секрет вручную.
3.  Передайте корневой сертификат CA через `--set privateCA=true`.

## Особенности эксплуатации

### Проверка готовности (Readiness)

Дождитесь завершения развертывания всех реплик:
```bash
kubectl rollout status deployment/rancher -n cattle-system
```

### Настройка Pod Security Admission (PSA)

Rancher v2.13+ полностью полагается на PSA. Для Management-кластера по умолчанию применяется профиль `privileged`, но для внутренних неймспейсов Rancher рекомендуется:
```bash
kubectl label namespace cattle-system pod-security.kubernetes.io/enforce=privileged
```

### Тюнинг etcd (Критично)

Для стабильности Rancher Server необходимо обеспечить `etcd` минимальные задержки дискового ввода-вывода.
*   **Fsync Latency:** должна быть < 10ms.
*   **Проверка:** используйте `fio` для замера производительности перед установкой.

## Дополнительная информация

### Жизненный цикл и миграция

*   **RKE1:** поддержка прекращена в июле 2025 года. Новые инсталляции на RKE1 запрещены.
*   **Backup:** используйте пакет `rancher-backup` (основан на Velero) для регулярного создания снимков состояния Management-кластера в S3.

---

**См. также:**

* [Rancher: Обзор платформы](./rancher_overview.md) — возможности и архитектура 2026.
* [Управление пользователями и RBAC](./rancher_rbac.md) — настройка после установки.
* [RKE в Rancher](./rancher_rke.md) — детали работы RKE2.
* [Установка cert-manager](../ToolsUtilities/cert_manager/installation.md) — глубокое руководство.

**Внешние ресурсы:**

* [Rancher Installation Guide (Official)](https://ranchermanager.docs.rancher.com/pages-for-subheaders/installation)
* [RKE2 Documentation](https://docs.rke2.io/)
