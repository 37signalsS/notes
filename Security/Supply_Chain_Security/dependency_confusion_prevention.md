# Защита от Dependency Confusion и подмены пакетов

**Актуально для:** npm 10+, pip ≥ 24.0, Go 1.22+, Trivy ≥ 0.71.0, Nexus 3.60+, Artifactory 7.90+, Harbor v2.15+, Kubernetes 1.31+

## Определения

* **Dependency Confusion (Подмена зависимостей):** Тип атаки на цепочку поставок, при котором злоумышленник публикует пакет с именем, совпадающим с внутренним приватным пакетом организации, в публичном реестре (npm, PyPI, RubyGems, crates.io). Приоритет публичного реестра в настройках менеджера пакетов приводит к установке вредоносного пакета вместо внутреннего.
* **Typosquatting (Тайпосквоттинг):** Публикация пакета с именем, отличающимся на 1–2 буквы от популярного (например, `reqeusts` вместо `requests`), в расчёте на опечатку при установке.
* **Namespace Confusion:** Случай, когда внутренний пакет организации не имеет уникального префикса (scope) в публичном реестре, что позволяет третьим лицам зарегистрировать пакет с тем же именем.
* **Private Registry Proxy:** Зеркальный реестр (Nexus, Artifactory, Harbor), проксирующий запросы к публичным реестрам и хранящий копии пакетов внутри периметра организации. Обеспечивает контроль, кэширование и сканирование.
* **Registry Scoping (Область видимости реестра):** Механизм менеджера пакетов, ограничивающий поиск пакетов определённым реестром для конкретного scope/namespace (например, `@myorg` в npm).
* **Lock-file poisoning:** Атака, при которой злоумышленник модифицирует lock-файл (package-lock.json, go.sum, Cargo.lock) для подмены зависимости на версию с бэкдором.
* **Supply Chain Integrity Violation:** Нарушение целостности поставки — изменение артефакта или зависимости на этапе сборки или установки без обнаружения.

## Предпосылки

Программное обеспечение и конфигурация, необходимые для настройки защиты от dependency confusion:

* **Package managers:** npm 10+ (Node.js 20+), pip ≥ 24.0 (Python 3.11+), Go 1.22+ (с модулями), Cargo 1.75+
* **Внутренний реестр:** Nexus 3.60+, Artifactory 7.90+, или Harbor v2.15+ с reverse proxy для npm/pip/go
* **Firewall:** iptables 1.8+ (Linux), pfSense 2.7+ (bare-metal), или Cilium 1.15+ (Kubernetes) для egress control
* **CI/CD:** GitLab CI 16+, Jenkins 2.462+, или GitHub Actions для pre-commit hooks
* **Сканирование:** Trivy ≥ 0.71.0 в CI для обнаружения подменённых пакетов
* **DNS:** Внутренний DNS-server (CoreDNS 1.11+, dnsmasq 2.80+, BIND 9.18+) для локального разрешения
* **Хранилище хешей:** Хранилище baseline SHA-256 хешей всех production-зависимостей (JSON/PostgreSQL)

### Требования к среде

* **Service-аккаунт в реестре:** scoped token с permissions `read,write` для internal-пакетов и `readonly` для proxied публичных.
* **Egress control policy:** по умолчанию `DENY all egress` на уровне firewall, с allowlist только для internal реестров.
* **Git hooks:** pre-commit и pre-push hooks обязательны для проверки lock-файлов.
* **Baseline SBOM:** для каждого сервиса сохраняется SBOM (CycloneDX JSON) перед деплоем в production.
* **Bare-metal/VM:** на физических серверах используется `/etc/hosts` fallback или локальный DNS для редиректа публичных реестров на internal proxy.

## Операции и команды

| Операция | Инструмент | Команда | Когда использовать |
| :--- | :--- | :--- | :--- |
| Проверка npm scope/registry | npm | `npm config get @mycorp:registry` | Верификация, что scope указывает на internal реестр |
| Проверка pip registry | pip | `pip config get global.index-url` | Верификация, что pip использует только internal PyPI |
| Проверка Go proxy | Go | `go env GOPROXY` | Верификация, что Go использует internal proxy |
| Проверка resolved packages | npm | `npm ls --json \| jq '.dependencies[].resolved'` | Обнаружение пакетов из публичных источников |
| Проверка lock-файла | npm | `npm ci --ignore-scripts` | Dry-run проверка integrity без установки |
| Сканирование на confusion | Trivy | `trivy fs --scanners vuln,config --severity CRITICAL,HIGH .` | CI/CD gate для обнаружения подозрительных пакетов |
| Bloкировка egress | iptables | `iptables -A OUTPUT -d npmjs.org -j REJECT` | Blokiрует прямой доступ к публичным реестрам на bare-metal |
| Bloкировка egress | NetworkPolicy | `kubectl apply -f restrict-egress.yaml` | Blokiрует egress в Kubernetes production namespace |
| Ротация scope в npm | npm | `npm org add myorg` | Регистрация нового scope для предотвращения подмены |
| Проверка Go модулей | Go | `go mod verify` | Верификация, что все модули прошли проверку |

## Основные концепции

### Механика атаки

Dependency confusion эксплуатирует два фактора:
1. **Приоритет реестра:** менеджер пакетов по умолчанию ищет пакет в публичном реестре первым, если иное не настроено.
2. **Отсутствие scope/префикса:** Внутренние пакеты организации не зарегистрированы в публичном реестре с уникальным именем.

**Пример атаки:**
```
Организация: MyCorp
Внутренний пакет: mycorp-internal-auth (не опубликован в npm)
Злоумышленник: публикует mycorp-internal-auth@1.0.0 в npm с бэкдором
Результат: npm install mycorp-internal-auth ставит вредоносный пакет
```

### Сравнение мер защиты

| Мера | Тип защиты | Сложность внедрения | Эффективность |
| :--- | :--- | :--- | :--- |
| **Scope/namespace в публичном реестре** | Превентивная | Низкая | Высокая (не даёт зарегистрировать чужое имя) |
| **Внутренний прокси-реестр** | Превентивная | Средняя | Очень высокая (контроль всех источников) |
| **Lock-файлы с хешами** | Детектирующая | Низкая | Высокая (обнаруживает подмену при установке) |
| **SCA-сканирование в CI** | Детектирующая | Средняя | Средняя (ловит известные CVE, не всегда — новые атаки) |
| **Pin по digest/version** | Превентивная | Низкая | Высокая (фиксация конкретного пакета) |
| **Файрвол/egress control** | Превентивная | Высокая | Очень высокая (блокирует прямой доступ к публичным реестрам) |

## Практические сценарии

### Сценарий 1: Настройка scope в npm

Регистрация уникального scope в публичном реестре блокирует возможность публикации пакетов под вашим именем третьими лицами.

```bash
# 1. Регистрация scope @mycorp в npm (одноразово)
# На https://www.npmjs.com/org/create создайте организацию @mycorp
# Это не даёт права на публикацию, но блокирует имя для других

# 2. Настройка .npmrc для проекта
# В корне проекта или в ~/.npmrc:
@mycorp:registry=https://registry.npmjs.org/
# Для внутренних пакетов указываем внутренний реестр
@mycorp:registry=https://nexus.internal/repository/npm-internal/
```

```bash
# 3. Установка с явным указанием реестра для scope
npm config set @mycorp:registry https://nexus.internal/repository/npm-internal/
npm install @mycorp/internal-auth
# → Установка ТОЛЬКО из внутреннего реестра
```

**Валидация:** Проверка, что пакет не приходит из публичного источника.

```bash
npm ls @mycorp/internal-auth --json | jq '.[] | .resolved'
# → "https://nexus.internal/repository/npm-internal/@mycorp/internal-auth/-/internal-auth-1.2.3.tgz"
```

### Сценарий 2: Настройка внутреннего реестра в pip (Python)

```bash
# 1. Настройка pip.conf (全局: /etc/pip.conf или ~/.pip/pip.conf)
cat > ~/.pip/pip.conf << 'EOF'
[global]
extra-index-url = https://nexus.internal/repository/pypi/simple/
index-url = https://nexus.internal/repository/pypi/simple/
trusted-host = nexus.internal
EOF

# 2. Для автоматического использования ТОЛЬКО внутреннего реестра
# (без fallback в публичный PyPI)
cat > ~/.pip/pip.conf << 'EOF'
[global]
index-url = https://nexus.internal/repository/pypi-remote/
trusted-host = nexus.internal
EOF
# → pip install requests обратится ТОЛЬКО к nexus.internal
```

```bash
# 3. Установка с явным указанием хешей (дополнительная защита)
pip install --require-hashes -r requirements.txt

# Требования к requirements.txt:
# requests==2.31.0 --hash=sha256:abcdef1234567890...
# urllib3==2.0.7 --hash=sha256:1234abcdef567890...
```

**Валидация:**

```bash
pip config get index-url
# → https://nexus.internal/repository/pypi-remote/
```

### Сценарий 3: Настройка Go proxy (внутренний)

```bash
# 1. Установка GOPROXY на внутренний прокси
export GOPROXY=https://nexus.internal/repository/go-proxy/,direct
# GONOSUMCHECK: помечает модули, для которых не нужно проверять checksum
# GONOSUMCHECK was deprecated in Go 1.13+ and removed in Go 1.16+
# Use GONOSUMDB and GOPRIVATE instead (GOPRIVATE implies GONOSUMDB)
export GONOSUMDB=mycorp.internal/*
export GOPRIVATE=mycorp.internal/*

# 2. Фиксация в go.env (автоматически применяется)
go env -w GOPROXY=https://nexus.internal/repository/go-proxy/,direct
# GONOSUMCHECK removed: use GONOSUMDB + GOPRIVATE (Go 1.16+)
go env -w GONOSUMDB=mycorp.internal/*
go env -w GOPRIVATE=mycorp.internal/*

# 3. Настройка .netrc для аутентификации (если Nexus требует)
cat > ~/.netrc << 'EOF'
machine nexus.internal
login ci-bot
password $NEXUS_TOKEN
EOF
chmod 600 ~/.netrc
```

```bash
# 4. Проверка конфигурации
go env GOPROXY
# → https://nexus.internal/repository/go-proxy/,direct

go env GOPRIVATE
# → mycorp.internal/*
```

### Сценарий 4: Настройка Harbor/Nexus как единого источника

```bash
# 1. Настройка DNS для перехвата публичных реестров (on-prem)
# В /etc/hosts или внутреннем DNS:
# registry.npmjs.org → nexus.internal
# registry-1.docker.io → harbor.internal

# 2. Firewall rules для блокировки прямого доступа
# iptables (Linux):
iptables -A OUTPUT -d registry.npmjs.org -j REJECT
iptables -A OUTPUT -d registry-1.docker.io -j REJECT
iptables -A OUTPUT -d pypi.org -j REJECT

# 3. Kubernetes: NetworkPolicy для ограничения доступа подов
cat <<'EOF' | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restrict-registry-access
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8  # внутренний реестр
      ports:
        - port: 443
          protocol: TCP
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
EOF
# → Поды в production могут обращаться ТОЛЬКО к внутреннему реестру
```

### Сценарий 5: Проверка lock-файлов перед коммитом

```bash
# 1. Проверка, что lock-файл актуален и не содержит подмен
# npm: проверка integrity в package-lock.json
npm ci --ignore-scripts
# → Использует ТОЛЬКО пакеты из lock-файла с проверкой хешей

# 2. Python: проверка хешей
pip install --require-hashes --check-hashes -r requirements.txt

# 3. Go: проверка модулей
go mod verify
# → all modules verified

# 4. Автоматизация через pre-commit hook
cat > .git/hooks/pre-commit << 'HOOK'
#!/bin/bash
# Проверка lock-файлов перед коммитом
if git diff --cached --name-only | grep -q "package.json"; then
    echo "Checking package-lock.json..."
    npm ls --json > /dev/null 2>&1 || {
        echo "ERROR: package-lock.json is out of sync"
        exit 1
    }
fi
HOOK
chmod +x .git/hooks/pre-commit
```

### Сценарий 6: CI/CD гейт — блокировка при обнаружении подмены

```yaml
# GitLab CI: проверка lock-файла и пакетов
dependency_integrity:
  stage: verify
  script:
    # Проверка, что все пакеты из ожидаемого реестра
    - npm ls --json | jq '.[] | .resolved' | grep -v "nexus.internal" && exit 1
    # Проверка хешей
    - npm ci --ignore-scripts --prefer-offline
    # Сканирование на dependency confusion
    - trivy fs --scanners vuln,config,secret --severity CRITICAL,HIGH .
  allow_failure: false
```

### Сценарий 7: SRE — мониторинг production на dependency confusion

SRE отвечает за то, чтобы ни один подменённый пакет не достиг production. Автоматизированная проверка:

```bash
# 1. Проверка SBOM production-образа на публичные пакеты
syft harbor.internal/myapp:v1.4.0 -o cyclonedx-json | \
  jq -r '.components[].supplier | select(.name != null)' | \
  while read pkg; do
    echo "WARNING: $pkg has no internal supplier"
  done

# 2. Correlate с baseline SBOM через GUAC
guac_query="SELECT artifact_name WHERE supplier_name!='mycorp' AND digest IN (SELECT digest FROM production_artifacts)"
# → список публичных пакетов в production (нарушение политики)

# 3. Alertmanager alert на обнаружение публичных пакетов:
cat > /etc/prometheus/rules/supply_chain.rules.yml << 'EOF'
groups:
- name: supply_chain
  rules:
  - alert: PublicPackageInProduction
    expr: kube_pod_info{namespace="production"} > 0 AND on(namespace)
      sbom_public_packages_total > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Public package detected in production SBOM"
      description: "{{ $labels.pod }} contains package from public registry"
EOF

# 4. Emergency: автоматический rollback при обнаружении
# Argo CD notification:
kubectl argo notifications trigger run app-health-trigger \
  --app-name my-application --recipient "slack:#incidents"
```

### Сценарий 8: Sysadmin — bare-metal сервер без Kubernetes

На физических серверах без NetworkPolicy используйте iptables + /etc/hosts fallback:

```bash
# 1. Блокировка egress на публичные реестры (iptables)
iptables -A OUTPUT -d registry.npmjs.org -j REJECT --reject-with icmp-host-prohibited
iptables -A OUTPUT -d pypi.org -j REJECT --reject-with icmp-host-prohibited
iptables -A OUTPUT -d pypi.python.org -j REJECT --reject-with icmp-host-prohibited
iptables -A OUTPUT -d proxy.golang.org -j REJECT --reject-with icmp-host-prohibited
iptables -A OUTPUT -d crates.io -j REJECT --reject-with icmp-host-prohibited

# 2. DNS-резолвинг через /etc/hosts (fallback для старых приложений)
echo "10.0.1.10 nexus.internal registry.npmjs.org pypi.org proxy.golang.org crates.io" >> /etc/hosts
# → все запросы к публичным реестрам резолвятся на internal Nexus

# 3. Мониторинг: Falco правило для обнаружения неожиданных скачков пакетов
cat > /etc/falco/rules.d/dependency_confusion.yaml << 'EOF'
- rule: Unexpected Package Download from Public Registry
  desc: Detect pip/npm/go downloading from public registry
  condition: >
    container not in (known_containers) and
    (proc.name in (pip, npm, go) and fd.name contains "registry.npmjs.org" or
     proc.name in (pip, npm, go) and fd.name contains "pypi.org")
  output: Package download from public registry (command=%proc.cmdline)
  priority: WARNING
EOF

# 4. Валидация: dry-run проверка, что ни один пакет не выходит наружу
for cmd in "npm install" "pip install" "go install"; do
  echo "Testing: $cmd"
  timeout 5 $cmd 2>&1 | grep -i "rejected\|error" && echo "✓ egress blocked"
done
```

## Лучшие практики

1. **Scope для каждого пакета:** Регистрируйте `@myorg` в npm, `myorg` в PyPI, `mycorp` в crates.io. Даже если пакеты публичные — scope блокирует подмену.
2. **Единый реестр:** Все зависимости проходят через внутренний прокси (Nexus/Artifactory). Прямой доступ к публичным реестрам блокируется firewall.
3. **Lock-файлы обязательны:** `package-lock.json`, `poetry.lock`, `go.sum`, `Cargo.lock` — коммитятся в Git и используются при установке (`npm ci`, `pip install --require-hashes`). Подробности: [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md#lock-файлы-практические-примеры).
4. **Pin по version:** Не используйте диапазоны (`^`, `~`) для критичных зависимостей. Фиксируйте точную версию.
5. **CI-проверка:** Каждый PR проверяет соответствие lock-файла и отсутствие пакетов из неожиданных источников.
6. **Deployment verification:** SRE проверяет SBOM production-деплоя против baseline перед выпуском. Автоматический rollback при обнаружении новых публичных пакетов в SBOM: `cyclonedx-diff baseline.json current-sboj.json && kubectl rollout undo`.
7. **Bare-metal egress control:** Sysadmin блокирует прямой egress на публичные реестры через iptables (`iptables -A OUTPUT -d pypi.org -j REJECT`). DNS-уровень резолва (`registry.npmjs.org → nexus.internal`) только как fallback для bare-metal серверов без firewall.
8. **Emergency response:** При обнаружении подмены — немедленная блокировка CI pipeline, аудит всех артефактов за последние 24 часа (`for art in $(trivy image --format json harbor.internal/myapp:latest | jq -r '.Results[].Vulnerabilities[].PkgName'); do ...`) и ротация всех scoped tokens.
9. **Checksum database pinning:** Go — фиксируйте `GOSUMDB` на внутренний сервер (`GOSUMDB=https://sum.golang.org` → `sumdb.internal`) для предотвращения downgrade attestation attacks.
10. **Pre-commit hooks:** Автоматическая проверка lock-файлов перед коммитом через `pre-commit` framework: `lock-file-audit`, `npm-integrity`, `pip-audit`.

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Пакет установлен из публичного реестра | Не настроен scope или proxy | `npm ls --json \| jq '.resolved'` | Настройте scope в `.npmrc` или proxy в package manager |
| `npm ci` падает с "Integrity check failed" | Lock-файл не синхронизирован | `npm install` → коммит lock-файл | Выполните `npm install` и закоммитьте обновлённый lock-файл |
| Pip ставит неправильную версию | `index-url` не настроен | `pip config get index-url` | Установите `index-url` на внутренний реестр в `pip.conf` |
| Go не может найти внутренний модуль | `GOPRIVATE` не настроен | `go env GOPRIVATE` | `go env -w GOPRIVATE=mycorp.internal/*` |
| CI падает с "checksum mismatch" | Go sumdb не настроен для internal | `go env GOSUMDB` | Установите `GOSUMDB=off` или на internal sumdb |
| Bare-metal: пакет всё ещё скачивается из публичного | /etc/hosts fallback не работает | `dig registry.npmjs.org` | Проверьте DNS resolution → должен указывать на nexus.internal |

## Граничные случаи и ограничения

* **Транзитивные зависимости:** Даже при использовании внутреннего реестра, прямые зависимости могут тянуть публичные транзитивные. Решение — зеркалирование всего дерева зависимостей через proxy-реестр.
* **Приватные пакеты без scope:** Если организация не зарегистрировала scope, любой может опубликовать пакет с тем же именем. Регистрация scope — бесплатная и не требует публикации пакетов.
* **Air-gapped среды:** При полной изоляции dependency confusion невозможен, но необходимо зеркалировать все зависимости через data diode или ручной копирование.
* **Mono-repo:** В мульти-репозиторных архитектурах внутренние пакеты могут ссылаться друг на друга. Необходимо настроить `GONOSUMDB` и `GOPRIVATE` для внутренних модулей (Go 1.16+; `GONOSUMCHECK` удалён).
* **SRE: production deployment verification:** SRE обязан проверять каждый deploy на наличие публичных пакетов в SBOM. Автоматизированный чек: `syft harbor.internal/myapp:$TAG -o cyclonedx-json | grep -c "registry.npmjs.org"`. Alert при значении > 0.
* **Sysadmin: bare-metal серверы без Kubernetes:** На физических серверах без NetworkPolicy используйте iptables egress control + `/etc/hosts` fallback. Проверка: `for pkg in $(pip list --format=json | jq -r '.[].name'); do pip show $pkg | grep "home-page" | grep -v "nexus.internal" && echo "ALERT: $pkg from public" >&2; done`.
* **DevOps: emergency pipeline shutdown:** При обнаружении подмены немедленно отключите pipeline и блокируйте egress: `kubectl patch netpol -n ci-cd deny-all-egress -p '{"spec":{"policyTypes":["Egress"]}}'` + `kubectl delete pod -n ci-cd -l job-name=dependency-scan`.
* **Multi-package-manager drift:** В monorepo с npm+pip+go версии lock-файлов могут расходиться. Используйте `pnpm` для npm, `pip-compile` для pip, `go mod tidy` для Go — и проверяйте в pre-commit: `lockfile-lint` для npm, `pipdeptree --warn fail` для Python, `go mod verify` для Go.
* **Registry proxy rate limits:** Nexus/Artifactory могут rate-limit публичные реестры. Настройте TTL cache: npm — `cache-min=300`, pip — `timeout = 10`, Go — `GOFLAGS=-mod=mod GOCACHE=/tmp/gocache`.
* **False positive prevention:** Scope-регистрация блокирует подмену имени, но злоумышленник может опубликовать пакет с похожим именем (`@mycorpo/internal-auth` вместо `@mycorp`). Решение: strict allowlist в Nexus (`npm.allowPublishPattern=@mycorp/*`) или Kyverno policy.

## Дополнительная информация

### Связанные документы

* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация компонентов.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз и общие принципы.
* [CI/CD атаки](../../CI-CD/DevSecOps/cicd_attacks.md) — классификация атак на пайплайны, включая dependency chain abuse.
* [Автоматизация обновлений](../../CI-CD/dependency_automation.md) — Renovate/Dependabot для безопасного обновления зависимостей.
* [Реагирование на инциденты цепочки поставок](./supply_chain_incident_response.md) — incident response playbook для dependency confusion, включая blast radius и rollback.
* [Анализ зависимостей и SBOM — Lock-файлы](./dependency_and_sbom_analysis.md#lock-файлы-практические-примеры) — детальная таблица методов проверки lock-файлов для npm, pip, Go, Cargo.
