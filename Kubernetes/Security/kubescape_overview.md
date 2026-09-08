# Kubescape: Мультидисциплинарный сканер безопасности Kubernetes

## Определения

**Kubescape** — открытый (Apache-2.0) сканер безопасности для экосистемы Kubernetes, разрабатываемый компанией ARMO. Инструмент объединяет несколько классов проверок в одном CLI: статический анализ YAML-манифестов, аудит работающего кластера (control-plane и workloads), сканирование образов на CVE и проверку конфигурации по фреймворкам (CIS, NSA-CISA, MITRE ATT&CK).

**Важно:** Kubescape **не тождественен** Kubesec. Это разные проекты от разных вендоров:

| Аспект | Kubesec | Kubescape |
| :--- | :--- | :--- |
| **Vendor** | ControlPlane | ARMO (позже — часть Linux Foundation/CNCF-экосистемы) |
| **Фокус** | SAST только YAML | SAST + runtime-аудит кластера + image scan |
| **Артефакт** | Числовой score | Отчёт с severity по фреймворкам + ресурсы |
| **Хранилище фреймворков** | Встроенный набор правил | Загружаемые controls (CIS, NSA-CISA, MITRE ATT&CK) |
| **Где описан в БЗ** | [kubesec.md](./kubesec.md) | (этот документ) |

---

## Основные концепции

### Архитектура и режимы работы

Kubescape — единый бинарь (`kubescape`), который в зависимости от подкоманды работает в одном из режимов:

| Режим | Команда | Что проверяется | Источник данных |
| :--- | :--- | :--- | :--- |
| **SAST YAML** | `kubescape scan` | Манифесты K8s до применения | Локальные файлы / stdin / Git-репозиторий |
| **Cluster audit** | `kubescape scan --submit` (deprecated) → `kubescape scan` (с `--server` API) | Конфигурация кластера, RBAC, NetworkPolicy, поды | kubeconfig + API-сервер |
| **Image scan** | `kubescape scan image <img>` | CVE в ОС-пакетах и зависимостях | Локальный daemon / registry |
| **Registry scan** | `kubescape scan registry <registry>` | Все образы в реджистри | Harbor, Docker Registry, ECR, GCR, ACR |
| **Repo scan** | `kubescape scan repository <repo>` | IaC + Dockerfile + манифесты | URL Git-репозитория |

В режиме image scan под капотом используется движок на базе [VulnList](https://github.com/kubescape/kubescape/tree/main/pkg/scan)-эквивалента: парсинг слоёв образа, матчинг версий пакетов с базой CVE. В отличие от чисто-VM-ориентированных Trivy/Grype, Kubescape извлекает дополнительный контекст из Kubernetes-манифеста, к которому относится образ (например, запущен ли контейнер от root), и **передаёт его в свой risk-engine**.

### Фреймворки (Controls)

Kubescape хранит политики в виде **frameworks** (наборов `Control`). Каждый control привязан к идентификатору фреймворка:

* **cis-kubernetes** — CIS Kubernetes Benchmark v1.6/v1.8 (разделы 1 — Control Plane, 5 — Policies).
* **nsa-cisa** — рекомендации NSA/CISA по Hardening Kubernetes.
* **mitre-attack** — маппинг обнаруженных проблем на техники MITRE ATT&CK.
* **devopsbest** — внутренняя best-practice база ARMO.

Загрузка фреймворков:

```bash
# Список доступных фреймворков
kubescape list frameworks

# Скачивание конкретного (нужно для офлайн-сканирования)
kubescape download framework cis-kubernetes --output /path/to/frameworks
```

После загрузки фреймворк используется через `--control`:

```bash
kubescape scan --control cis-kubernetes-1.6
```

### Формат вывода

Основные форматы: `json`, `junitxml`, `pretty` (по умолчанию), `pdf` (отчёт).

JSON-структура результатов image scan (используется в интеграционных скриптах):

```json
{
  "matches": [
    {
      "vulnerability": {
        "id": "CVE-2024-12345",
        "severity": "Critical",
        "packageName": "libssl3",
        "packageVersion": "3.0.2-1"
      },
      "resource": {
        "kind": "Pod",
        "name": "my-app-7d4f-abc"
      }
    }
  ]
}
```

Для извлечения CVE-списка из такого отчёта:

```bash
jq -r '.matches[].vulnerability.id' result.json | grep -E '^CVE-'
```

### Severity и приоритизация

Kubescape использует стандартную шкалу CVSS-категорий: `Critical`, `High`, `Medium`, `Low`, `Negligible`, `Unknown`. Дополнительно risk-engine агрегирует "reachability" (достижимость уязвимости в runtime) и "asset-criticality", формируя итоговый risk-score в UI ARMO (в CLI-режиме доступен через флаг `--score`).

### Хранение состояния (Storage Backend)

Для cluster-audit режима Kubescape поддерживает backend:

* **`--submit`** (deprecated в новых версиях): отправка отчётов в облако ARMO.
* **`--server <url>`**: подключение к локальному Kubescape-operator / KS-серверу.
* **Локальный JSON**: режим по умолчанию, без долгосрочного хранения.

В рамках DevSecOps-пайплайнов чаще всего используется чисто локальный режим с выгрузкой артефактов (`--output`) для последующего анализа.

### Ограничения инструмента

* **Зависимость от базы CVE:** при отсутствии сетевого доступа требуется предварительная загрузка (`kubescape download`). Устаревшая база ведёт к ложным "clean" отчётам.
* **Не заменяет Trivy:** для image-only сканирования в CI чаще выбирают Trivy из-за скорости и меньшего потребления памяти. Kubescape оправдан, когда нужен **кластерный контекст** (связь CVE↔манифест).
* **Image scan требует работающего демона container runtime:** по умолчанию `docker`; для `containerd`/`CRI-O` нужен флаг `--container-runtime` и дополнительная настройка сокетов.
* **Отсутствие VEX-поддержки в open-source версии:** VEX-аттестации (см. [Сканирование Docker-образов на уязвимости](../../Docker/Docker_security/vulnerability_scanning.md)) обрабатываются только в коммерческой платформе ARMO.
* **RBAC для cluster scan:** требует минимум read-only доступ ко всем namespace (ClusterRole `view` или эквивалент).

---

## Практические сценарии

### Установка

```bash
# Linux/macOS — установка скриптом
curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash

# Через менеджер пакетов (brew)
brew install kubescape

# Проверка
kubescape version
# → kubescape version: v3.0.34

# Скачивание дефолтных фреймворков
kubescape download framework nsa-cisa --output ~/.kubescape/frameworks
```

### Сканирование YAML-манифестов (SAST)

```bash
# Сканирование директории
kubescape scan --path ./k8s --control cis-kubernetes-1.6

# Сканирование одного файла
kubescape scan -f deployment.yaml

# Только критические находки, без warning'ов
kubescape scan --path ./k8s --severity-threshold Critical
```

### Сканирование кластера

```bash
# Полный аудит кластера по NSA-CISA + CIS
kubescape scan --control cis-kubernetes-1.6,nsa-cisa --format json --output cluster-report.json

# Аудит только workloads одного namespace
kubescape scan --namespace production --format pretty
```

### Сканирование образов

```bash
# Локальный образ
kubescape scan image nginx:1.25 --format json --output nginx.json

# Удалённый образ из registry
kubescape scan image registry.example.com/myorg/myapp:v1.2.3 --format json

# Все образы из реджистри (ограниченно — нужен список)
kubescape scan registry registry.example.com --all
```

### Интеграция в CI/CD

#### GitHub Actions

```yaml
name: kubescape-scan
on: [pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run KubeSAST + Image scan
        run: |
          curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash
          kubescape scan --path ./manifests --format junitxml --output kubescape-junit.xml --severity-threshold High
      - name: Upload test results
        uses: actions/upload-artifact@v4
        with:
          name: kubescape-report
          path: kubescape-junit.xml
```

### Комбинирование с Trivy и kube-bench

Kubescape пересекается по зонам покрытия с [Trivy](../../Docker/Docker_security/vulnerability_scanning.md) (image CVE) и [kube-bench](./kube-bench.md) (CIS host checks). Практическая схема для production:

| Слой | Инструмент | Почему |
| :--- | :--- | :--- |
| **Node OS / Control Plane host** | `kube-bench` | Прямая проверка процессов и флагов kubelet |
| **Image CVE** | `trivy image` | Скорость, широкая база, VEX |
| **Cluster configuration / RBAC / NSA** | `kubescape scan` | Framework-driven, единый отчёт |
| **YAML SAST в IDE/CI** | `kubescape scan -f` или `kubesec` | Shift-left |

---

### Скрипт автоматического эксплойт-поиска (kubescape + metasploit)

**Назначение:** образовательный PoC для red team / пентест-лабораторий. Сканирует все образы работающих подов через `kubescape`, извлекает CVE из отчётов и автоматически ищет готовые модули эксплойтов в Metasploit Framework. Используйте **только в изолированных лабораториях или на собственных ресурсах**. Применение против чужих систем — уголовное преступление (ст. 272–274 УК РФ, аналоги — Computer Fraud and Abuse Act, GDPR-обязательства по уведомлению).

#### Архитектура скрипта

```
kubectl get pods → список образов
        │
        ▼
kubescape scan image <image> → JSON-отчёты (scans/<ts>/results/*.json)
        │
        ▼
jq извлекает CVE → scans/<ts>/cve_list.txt
        │
        ▼
msfconsole search CVE → scans/<ts>/metasploit_results.txt
```

Каждый этап — отдельный отказоустойчивый шаг: пропуск Metasploit (если не установлен) или пропуск CVE-извлечения (если отчёт пуст) не ломает весь пайплайн.

#### Полный скрипт

```bash
#!/bin/bash
# kubescape-to-metasploit.sh
# Educational PoC: scan cluster images → extract CVEs → search Metasploit exploits.
# Use ONLY in isolated labs on assets you own.

DEFAULT_SCAN_NAME=$(date +"%Y-%m-%d_%H-%M-%S")
read -p "Enter a name for this scan (leave empty for default: $DEFAULT_SCAN_NAME): " SCAN_NAME
SCAN_NAME=${SCAN_NAME:-$DEFAULT_SCAN_NAME}

SCAN_DIR="scans/$SCAN_NAME"
mkdir -p "$SCAN_DIR"
echo "[+] Scan results will be stored in: $SCAN_DIR"

echo "[+] Checking for required tools..."

if ! command -v kubescape &> /dev/null; then
    echo "[-] Kubescape is not installed. Please install it first."
    exit 1
fi

echo "[+] Checking current Kubernetes context..."
CURRENT_CONTEXT=$(kubectl config current-context)
if [ -z "$CURRENT_CONTEXT" ]; then
    echo "[-] No active Kubernetes context found. Please configure your kubeconfig."
    exit 1
fi
echo "[+] You are currently using Kubernetes context: $CURRENT_CONTEXT"

read -p "Do you want to continue with this context? (y/n): " CONTINUE
if [[ "$CONTINUE" != "y" && "$CONTINUE" != "Y" ]]; then
    echo "[-] Exiting script."
    exit 0
fi

read -p "Enter the namespace to scan (leave empty for all namespaces): " NAMESPACE
if [[ -z "$NAMESPACE" ]]; then
    NAMESPACE_FLAG="--all-namespaces"
    echo "[+] Scanning all namespaces..."
else
    NAMESPACE_FLAG="-n $NAMESPACE"
    echo "[+] Scanning namespace: $NAMESPACE"
fi

read -p "Do you want to check Metasploit for available exploits? (y/n): " CHECK_METASPLOIT
if [[ "$CHECK_METASPLOIT" == "y" || "$CHECK_METASPLOIT" == "Y" ]]; then
    SEARCH_METASPLOIT=true
    if ! command -v msfconsole &> /dev/null; then
        echo "[-] Metasploit is not installed. Exploit search will be skipped."
        SEARCH_METASPLOIT=false
    fi
else
    SEARCH_METASPLOIT=false
    echo "[+] Skipping Metasploit exploit search."
fi

echo "[+] Retrieving container images..."
kubectl get pods $NAMESPACE_FLAG -o json | jq -r '.items[].spec.containers[].image' | sort -u > "$SCAN_DIR/images.txt"

if [[ ! -s "$SCAN_DIR/images.txt" ]]; then
    echo "[-] No container images found in the selected namespace(s)."
    exit 1
fi

echo "[+] Found $(wc -l < "$SCAN_DIR/images.txt") unique images."

echo "[+] Scanning container images with Kubescape..."
mkdir -p "$SCAN_DIR/results"

while read -r image; do
    echo "[*] Scanning $image..."
    safe_name=$(echo "$image" | tr '/:' '_')
    kubescape scan image "$image" --format json --output "$SCAN_DIR/results/${safe_name}.json"
done < "$SCAN_DIR/images.txt"

echo "[+] Extracting CVEs from Kubescape reports..."
jq -r '.matches[].vulnerability.id' "$SCAN_DIR/results/"*.json | grep CVE > "$SCAN_DIR/cve_list.txt"

if [[ ! -s "$SCAN_DIR/cve_list.txt" ]]; then
    echo "[-] No CVEs found in container images."
    exit 0
fi

echo "[+] Found $(wc -l < "$SCAN_DIR/cve_list.txt") CVEs."

if [[ "$SEARCH_METASPLOIT" == true ]]; then
    echo "[+] Searching for exploits in Metasploit..."
    rm -f "$SCAN_DIR/metasploit_results.txt"

    while read -r cve; do
        echo "[*] Searching for $cve in Metasploit..."
        msfconsole -q -x "search $cve; exit" | tee -a "$SCAN_DIR/metasploit_results.txt"
    done < "$SCAN_DIR/cve_list.txt"

    echo "[+] Search completed. Found exploits:"
    grep -E 'exploit/' "$SCAN_DIR/metasploit_results.txt" || echo "[-] No exploits found for detected CVEs."
else
    echo "[+] Skipping Metasploit exploit search."
fi

echo "[+] Scan completed. Results are stored in: $SCAN_DIR"
```

#### Ожидаемые результаты

```
[+] Scan results will be stored in: scans/2025-02-16_22-15-30
[+] Checking for required tools...
[+] Checking current Kubernetes context...
[+] You are currently using Kubernetes context: kind-lab
[+] Scanning all namespaces...
[+] Retrieving container images...
[+] Found 7 unique images.
[+] Scanning container images with Kubescape...
[*] Scanning nginx:1.25...
[*] Scanning redis:7-alpine...
[+] Found 23 CVEs.
[+] Searching for exploits in Metasploit...
[*] Searching for CVE-2024-12345 in Metasploit...
   0  exploit/multi/http/nginx_alias_traversal  2024-xx-xx  excellent  No  Nginx Alias Traversal
[+] Search completed. Found exploits:
   0  exploit/multi/http/nginx_alias_traversal  2024-xx-xx  excellent  No  Nginx Alias Traversal
```

#### Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `kubescape scan image ...` падает с `permission denied /var/run/docker.sock` | Нет доступа к Docker-демону | Добавьте пользователя в группу `docker` или используйте rootless-режим |
| `msfconsole -q -x "search ..."` возвращает пусто | CVE не имеет модуля в Metasploit | Ожидаемо — Metasploit покрывает < 30% CVE. Используйте `searchsploit` (offline) или `nuclei templates` |
| `jq: error: Cannot iterate over null` | Образ не содержит `.matches` (пустой отчёт) | Добавьте `if .matches then ... end` в пайплайн или `jq -r '.matches // [] | ...'` |
| Скрипт сканирует дублирующиеся образы | `sort -u` уже есть, но образы с разными тегами — разные | Замените `sort -u` на `awk -F: '{print $1}' | sort -u` для дедупликации по реестри+имени |
| `kubescape` запрашивает фреймворк при офлайн-старте | Нет сети для скачивания | `kubescape download framework nsa-cisa,cis-kubernetes-1.6 --output ./frameworks` |
| `kubectl config current-context` возвращает пусто | Нет активного контекста | `kubectl config use-context <name>` или `KUBECONFIG=...` |

#### Best Practices

1. **Изолированный kubeconfig:** используйте отдельный контекст (`kind-lab`, `minikube`) — никогда не запускайте скрипт против production.
2. **Offline-база CVE:** перед сканированием `kubescape download` для воспроизводимости и офлайн-работы.
3. **EPSS-фильтр:** расширьте скрипт фильтром по [EPSS](https://www.first.org/epss/) — пропускайте CVE с EPSS < 0.1, чтобы сократить шум.
4. **Параллелизация image scan:** цикл `while read` — последовательный. Для ускорения замените на `xargs -P 4 -I {} ...` (осторожно с rate-limits registry).
5. **Не злоупотребляйте Metasploit:** запуск `msfconsole` для каждой CVE — дорогая операция (5–10 сек на старт). Используйте `searchsploit` (offline) или прямой `msf6 -e 'search ...' -q` в batch.
6. **Логирование:** добавьте `exec > >(tee -a "$SCAN_DIR/scan.log") 2>&1` в начало скрипта для аудита действий.

#### Edge Cases и ограничения

* **Не покрывает runtime-only уязвимости:** CVE, проявляющиеся только при определённой последовательности API-вызовов (например, race conditions), скрипт не обнаружит.
* **Ложные срабатывания Kubescape:** некоторые CVE могут быть помечены как Critical, но не быть эксплуатируемыми в вашем контексте (см. [VEX](../../Docker/Docker_security/vulnerability_scanning.md)).
* **Отсутствие эксплойта ≠ отсутствие уязвимости:** Metasploit содержит модули для малой доли CVE. Используйте дополнительно [Nuclei](https://github.com/projectdiscovery/nuclei), [Vulners](https://vulners.com/), ручной анализ.
* **Network-egress:** `msfconsole search` может ходить в Metasploit Cloud — в изолированной лаборатории используйте локальный `msfdb` и offline `searchsploit`.
* **CVE в init containers пропускается:** текущий `jq -r '.items[].spec.containers[].image'` берёт только основные контейнеры. Добавьте `.items[].spec.initContainers[].image` для полноты.

---

## Дополнительная информация

### Сравнение с инструментами (2025–2026)

| Инструмент | Фокус | Сильные стороны | Когда выбирать |
| :--- | :--- | :--- | :--- |
| **Kubescape** | K8s cluster + image + frameworks | Единый бинарь, NSA/CISA/MITRE из коробки | Cluster-wide аудит с привязкой к фреймворкам |
| **Trivy** | Image / IaC / SBOM | Скорость, широкая база CVE, VEX | CI/CD для image-only |
| **kube-bench** | Node OS / kubelet config | CIS host-checks | Аудит узлов |
| **Kubesec** | YAML SAST | Минималистичный, быстрый | Pre-commit, IDE |

### Compliance Mapping

| Стандарт | Покрытие | Конкретные controls |
| :--- | :--- | :--- |
| **CIS Kubernetes Benchmark v1.8** | Частичное | cis-kubernetes-1.8 framework (5.x) |
| **NSA-CISA Kubernetes Hardening** | Полное | nsa-cisa framework |
| **MITRE ATT&CK for Containers** | Частичное | mitre-attack framework |
| **SOC 2 (CC6.1, CC7.1)** | Косвенное | RBAC + audit через cluster scan |

### Полезные ссылки

* [Официальный репозиторий Kubescape](https://github.com/kubescape/kubescape)
* [Документация ARMO](https://docs.armosec.io/)
* [Список frameworks и их contents](https://hub.armosec.io/)
* [Metasploit Framework](https://github.com/rapid7/metasploit-framework)

### Связанные темы

* [Kubesec: SAST YAML](./kubesec.md) — лёгкий SAST, не путать с Kubescape.
* [kube-bench](./kube-bench.md) — проверка конфигурации узлов (CIS).
* [Trivy: сканирование образов](../../Docker/Docker_security/vulnerability_scanning.md) — альтернатива для image-only.
* [RBAC: обзор](./rbac/rbac_overview.md) — `kubescape` упоминается как инструмент аудита RBAC.
* [Pod Security Context](./pod_security_context.md) — runtime-аспекты безопасности подов.
* [Аудит событий](./audit.md) — логирование и трассируемость.