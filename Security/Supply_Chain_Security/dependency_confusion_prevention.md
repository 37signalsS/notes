# Защита от Dependency Confusion и подмены пакетов

## Определения

* **Dependency Confusion (Подмена зависимостей):** Тип атаки на цепочку поставок, при котором злоумышленник публикует пакет с именем, совпадающим с внутренним приватным пакетом организации, в публичном реестре (npm, PyPI, RubyGems, crates.io). Приоритет публичного реестра в настройках包管理щика приводит к установке вредоносного пакета вместо внутреннего.
* **Typosquatting (Тайпосквоттинг):** Публикация пакета с именем, отличающимся на 1–2 буквы от популярного (например, `reqeusts` вместо `requests`), в расчёте на опечатку при установке.
* **Namespace Confusion:** Случай, когда внутренний пакет организации не имеет уникального префикса (scope) в публичном реестре, что позволяет третьим лицам зарегистрировать пакет с тем же именем.
* **Private Registry Proxy:** Зеркальный реестр (Nexus, Artifactory, Harbor), проксирующий запросы к публичным реестрам и хранящий копии пакетов внутри периметра организации. Обеспечивает контроль, кэширование и сканирование.
* **Registry Scoping (Область видимости реестра):** Механизм包管理щика, ограничивающий поиск пакетов определённым реестром для конкретного scope/namespace (например, `@myorg` в npm).

## Основные концепции

### Механика атаки

Dependency confusion эксплуатирует два фактора:
1. **Приоритет реестра:**包管理щик по умолчанию ищет пакет в публичном реестре первым, если иное не настроено.
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

### Сценарий 3: Настройка Go proxy ( внутренний)

```bash
# 1. Установка GOPROXY на внутренний прокси
export GOPROXY=https://nexus.internal/repository/go-proxy/,direct
export GONOSUMCHECK=mycorp.internal/*
export GONOSUMDB=mycorp.internal/*
export GOPRIVATE=mycorp.internal/*

# 2. Фиксация в go.env (автоматически применяется)
go env -w GOPROXY=https://nexus.internal/repository/go-proxy/,direct
go env -w GONOSUMCHECK=mycorp.internal/*
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
    - trivy fs --security-checks vuln --severity CRITICAL .
  allow_failure: false
```

## Лучшие практики

1. **Scope для каждого пакета:** Регистрируйте `@myorg` в npm, `myorg` в PyPI, `mycorp` в crates.io. Даже если пакеты публичные — scope блокирует подмену.
2. **Единый реестр:** Все зависимости проходят через внутренний прокси (Nexus/Artifactory). Прямой доступ к публичным реестрам блокируется firewall.
3. **Lock-файлы обязательны:** `package-lock.json`, `poetry.lock`, `go.sum`, `Cargo.lock` — коммитятся в Git и используются при установке (`npm ci`, `pip install --require-hashes`).
4. **Pin по version:** Не используйте диапазоны (`^`, `~`) для критичных зависимостей. Фиксируйте точную версию.
5. **CI-проверка:** Каждый PR проверяет соответствие lock-файла и отсутствие пакетов из неожиданных источников.

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Пакет установлен из публичного реестра | Не настроен scope или proxy | `npm ls --json \| jq '.resolved'` | Настройте scope в `.npmrc` или proxy в包管理щике |
| `npm ci` падает с " Integrity check failed" | Lock-файл не синхронизирован | `npm install` → коммит lock-файл | Выполните `npm install` и закоммитьте обновлённый lock-файл |
| Pip ставит неправильную версию | `index-url` не настроен | `pip config get index-url` | Установите `index-url` на внутренний реестр в `pip.conf` |
| Go не может найти внутренний модуль | `GOPRIVATE` не настроен | `go env GOPRIVATE` | `go env -w GOPRIVATE=mycorp.internal/*` |

## Граничные случаи и ограничения

* **Транзитивные зависимости:** Даже при использовании внутреннего реестра, прямые зависимости могут тянуть публичные транзитивные. Решение — зеркалирование всего дерева зависимостей через proxy-реестр.
* **Приватные пакеты без scope:** Если организация не зарегистрировала scope, любой может опубликовать пакет с тем же именем. Регистрация scope — бесплатная и не требует публикации пакетов.
* **Air-gapped среды:** При полной изоляции dependency confusion невозможен, но необходимо зеркалировать все зависимости через data diode или ручной копирование.
* **Mono-repo:** В мульти-репозиторных архитектурах внутренние пакеты могут ссылаться друг на друга. Необходимо настроить `GONOSUMCHECK` и `GONOSUMDB` для внутренних модулей.

## Дополнительная информация

### Связанные документы

* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация компонентов.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз и общие принципы.
* [CI/CD атаки](../../CI-CD/DevSecOps/cicd_attacks.md) — классификация атак на пайплайны, включая dependency chain abuse.
* [Автоматизация обновлений](../../CI-CD/dependency_automation.md) — Renovate/Dependabot для безопасного обновления зависимостей.
