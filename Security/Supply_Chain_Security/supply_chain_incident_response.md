# Реагирование на инциденты безопасности цепочки поставок

**Актуально для:** Trivy ≥ 0.71.0, Cosign v3.1.3, Rekor v1.4+, Kyverno v1.19+, Harbor v2.15+, Kubernetes 1.31+, SLSA v1.2, CycloneDX 1.7, SPDX 3.0, GUAC v1.x, Falco (eBPF) 0.38+, Cilium Tetragon 0.14+

## Определения

* **Supply Chain Incident (Инцидент цепочки поставок):** Событие, при котором скомпрометирован один из компонентов жизненного цикла ПО: зависимость, базовый образ, инструмент сборки, ключ подписи или CI/CD-пайплайн. Типичные примеры — вредоносный код в обновлённой библиотеке, подмена Docker-образа, компрометация ключа Cosign.
* **Blast Radius (Радиус поражения):** Масштаб затронутых сервисов и сред. Определяется по графу зависимостей (SBOM) и топологии деплоя.
* **Rollback (Откат):** Возврат к предыдущей verified версии артефакта с подтвержденной целостностью (подпись + SBOM + VSA).
* **Key Compromise (Компрометация ключа):** Утечка приватного ключа подписи, позволяющая злоумышленнику подписывать вредоносные артефакты от имени организации.
* **Postmortem (Постмортем):** Анализ после инцидента без поиска виноватых (blameless), фокусирующийся на корневых причинах и мерах по предотвращению повторения.
* **SEV (Severity):** Классификация инцидента по степени критичности: SEV-1 — немедленное вмешательство, SEV-2 — в течение 4 часов, SEV-3 — в течение 24 часов.
* **Triage (Триаж):** Быстрая оценка инцидента: идентификация типа, SEV-уровня, blast radius и выбор стратегии ответа (откат / hotfix / мониторинг).

## Основные концепции

### Типология инцидентов supply chain

| Тип инцидента | SEV | Признаки | Источник обнаружения |
| :--- | :--- | :--- | :--- |
| **Уязвимая зависимость в продакшене** | SEV-2/3 | CVE в компоненте, используемом сервисом | Trivy/Grype, алерты NVD, мониторинг |
| **Компрометация зависимость (malicious package)** | SEV-1 | Бэкдор в обновлённой библиотеке | SCA-сканер, аномалии в runtime, аудит кода |
| **Подмена Docker-образа** | SEV-1 | Образ без подписи или с невалидной подписью | Admission-контролер, Kyverno |
| **Компрометация ключа подписи** | SEV-1 | Подпись невалидна или принадлежит неизвестному ключу | cosign verify, аудит Rekor |
| **Отравление CI/CD пайплайна** | SEV-1 | Изменение в .gitlab-ci.yml / Jenkinsfile / workflow | Git-аудит, code review |
| **Подмена SBOM/VEX** | SEV-2 | SBOM не соответствует реальному составу образа | trivy diff, сравнение эталона |
| **Компрометация базового образа** | SEV-1 | CVE или бэкдор в базовом образе (alpine, distroless) | Trivy, аудит Dockerfile |

### Жизненный цикл реагирования

```
1. ОБНАРУЖЕНИЕ
   ├── Алерт из Trivy/Grype (новая CVE)
   ├── Аномалия в Runtime (Falco, Tetragon)
   ├── Внешнее уведомление (vendor advisory, NVD)
   └── Аудит (проверка подписей, SBOM)

2. ОЦЕНКА (в первые 15 минут)
   ├── Определение типа инцидента
   ├── Определение SEV-уровня
   ├── Определение Blast Radius (какие сервисы затронуты)
   └── Решение: откат / горячий фикс / мониторинг

3. ЛОКАЛИЗАЦИЯ
   ├── Блокировка деплоя затронутых образов
   ├── Карантин скомпрометированных подов (NetworkPolicy)
   ├── Ротация секретов (если скомпрометирован ключ)
   └── Уведомление команд

4. УСТРАНЕНИЕ
   ├── Горячий фикс (патч зависимости + пересборка)
   ├── Или откат к предыдущейverified версии
   ├── Обновление SBOM и VEX
   └── Проверка подписей

5. ВОССТАНОВЛЕНИЕ
   ├── Деплой исправленного артефакта
   ├── Верификация (подпись + SBOM + VSA)
   ├── Мониторинг на предмет повторного инцидента
   └── Обновление политик

6. ПОСМОРТЕМ
   ├── Blameless analysis (5 Whys)
   ├── Timeline инцидента
   ├── Action items с владельцами и сроками
    └── Обновление runbook
```

## Предпосылки

Программное обеспечение и сервисы, необходимые для выполнения сценариев реагирования:

* **Сканирование образов:** Trivy ≥ 0.71.0 (в CI/CD и на хосте для адресной проверки).
* **Подпись и верификация:** Cosign v3.1.3 (Keyless через Sigstore или внутренний Fulcio/Rekor), `rekor-cli` v1.4+ для аудита Transparency Log.
* **Контроль доступа:** Kyverno v1.19+ с ClusterPolicy для немедленной блокировки неподписанных образов.
* **Граф зависимостей:** GUAC v1.x — определение blast radius через reverse dependency queries.
* **Runtime наблюдаемость:** Falco (eBPF) 0.38+ или Cilium Tetragon 0.14+ для обнаружения аномальной загрузки библиотек и egress traffic.
* **Реестр артефактов:** Harbor v2.15+ с OCI Referrers API для хранения аттестаций и SBOM.
* **CI/CD:** GitLab Runner 16+, Jenkins 2.462+, или Tekton — с доступом к Harbor API для массовой проверки тегов.

### Требования к среде

* **Доступ к Harbor API:** service-аккаунт с scope `pull,delete` для массовых проверок образов.
* **Kubectl доступ:** role `admin` или `edit` в production namespace для выполнения `kubectl rollout undo`.
* **NetworkPolicy controller:** Calico или Cilium для мгновенной блокировки egress трафика скомпрометированных подов.
* **Хранилище журналов:** централизованный сбор логов CI/CD (syslog-ng/Loki) для корреляции подозрительных egress-соединений.
* **Hardware:** AES-NI для ускорения TLS в инфраструктуре подписи; минимум 4 ГБ RAM для работы Trivy DB в CI runner'е.

## Операции и команды

| Операция | Инструмент | Команда | Когда использовать |
| :--- | :--- | :--- | :--- |
| Проверка подписи образа | Cosign | `cosign verify <image> --certificate-identity-regexp "<url>" --certificate-oidc-issuer "<issuer>"` | Обнаружение подмены образа или компрометации ключа |
| Проверка provenance | Cosign | `cosign verify-attestation --type slsaprovenance <image>` | Верификация SLSA attestation перед деплоем |
| Поиск артефактов по ключу | rekor-cli | `rekor-cli search --public-key cosign.pub --format json` | Выявление всех образов, подписанных скомпрометированным ключом |
| Поиск артефакта в Rekor | rekor-cli | `rekor-cli search --artifact <image> --format json` | Аудит истории подписи конкретного образа |
| Сканирование образа на CVE | Trivy | `trivy image <image> --vuln $CVE` | Адресная проверка на конкретную уязвимость |
| Массовая проверка CVE | Trivy + jq | `for img in $images; do trivy image --format json --vuln $CVE $img > out.json; done` | Выявление всех затронутых образов (blast radius) |
| Генерация SBOM | Syft | `syft <image> -o cyclonedx-json > sbom.json` | Инвентаризация для анализа зависимостей |
| Выпуск VEX | cyclonedx-cli | `cyclonedx-cli merge --input-files vex-template.xml out.xml --output-file vex.xml` | Подавление ложных срабатываний после triage |
| Bloкировка образа | Kyverno | `kubectl apply -f block-compromised-key.yaml` | Немедленная блокировка деплоя на уровне admission |
| Откат деплоя | kubectl | `kubectl rollout undo deployment/<app> -n production` | Возврат к last-known-good состоянию |
| Bloкировка egress пода | NetworkPolicy | `kubectl apply -f isolate-pods.yaml` | Карантин скомпрометированного пода |
| Генерация нового ключа | Cosign | `cosign generate-key-pair` | Ротация после компрометации ключа |
| Переподпись образа | Cosign | `cosign sign --yes <image>` | Восстановление после ротации ключа |

## Практические сценарии

### Сценарий 1: Новая CVE в продакшене — пошаговый response

```bash
# 1. ОБНАРУЖЕНИЕ: Получение CVE ID
CVE="CVE-2024-EXAMPLE"
COMPONENT="requests"
AFFECTED_VERSION="2.31.0"
FIXED_VERSION="2.32.0"

# 2. ОЦЕНКА: Проверка, затронут ли наш сервис
trivy image harbor.internal/my-app:v1.2.3 --vuln $CVE
# → requests  2.31.0  2.32.0  CRITICAL

# 3. ОЦЕНКА: Reachability — вызывается ли уязвимый код?
#    (Grype OSS не имеет --show-vulnerability-reachability; используйте govulncheck для Go или VEX с code_not_reachable)
govulncheck ./...
# → CVE-2024-EXAMPLE: REACHABLE

# 4. ОЦЕНКА: Blast Radius — какие сервисы используют эту версию?
for img in $(curl -s -u admin:$HARBOR "https://harbor.internal/api/v2.0/projects/myapp/repositories" | jq -r '.[].name'); do
  vuln=$(trivy image --format json "harbor.internal/$img:latest" | jq --arg c "$CVE" '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c)')
  [ -n "$vuln" ] && echo "AFFECTED: $img"
done
# → AFFECTED: my-app
# → AFFECTED: my-worker

# 5. РЕШЕНИЕ: Critical + Reachable → горячий фикс
# Создание ветки hotfix
git checkout -b hotfix/$CVE
# Обновление зависимости
sed -i 's/requests==2.31.0/requests==2.32.0/' requirements.txt
pip install -r requirements.txt
# Коммит и пуш
git add requirements.txt
git commit -m "fix: upgrade requests to $FIXED_VERSION (hotfix $CVE)"
git push origin hotfix/$CVE
# CI/CD автоматически соберёт новый образ с SBOM и подписью
```

### Сценарий 2: Компрометация ключа подписи

```bash
# 1. ОБНАРУЖЕНИЕ: cosign verify возвращает ошибку
cosign verify harbor.internal/my-app:v1.2.3 \
  --certificate-identity-regexp "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer "https://harbor.internal"
# → ERROR: no matching signatures found

# 2. ЛОКАЛИЗАЦИЯ: Блокировка всех образов, подписанных этим ключом
# Проверка в Rekor, какие артефакты были подписаны
rekor-cli search --public-key cosign.pub --format json | jq '.[].UUID'
# → ["uuid1", "uuid2", "uuid3"]

# 3. ЛОКАЛИЗАЦИЯ: Блокировка деплоя
kubectl apply -f - <<'EOF'
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: block-compromised-key
spec:
  validationFailureAction: Enforce
  rules:
    - name: reject-compromised-signature
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["harbor.internal/*"]
          reject: true
          message: "Key compromised — blocked pending rotation"
EOF

# 4. УСТРАНЕНИЕ: Ротация ключей
# Генерация новой ключевой пары
cosign generate-key-pair

# Обновление ключа в Kyverno
kubectl patch clusterpolicy block-compromised-key --type merge -p '{
  "spec": {"rules": [{"name": "reject-compromised-key", "verifyImages": [{"imageReferences": ["harbor.internal/*"], "attestors": [{"entries": [{"keys": {"publicKeys": "'"$(cat cosign.pub)"'"}}]}]}]}]}
}'

# 5. ВОССТАНОВЛЕНИЕ: Переподпись всех активных артефактов
for img in $(curl -s -u admin:$HARBOR "https://harbor.internal/api/v2.0/projects/myapp/repositories" | jq -r '.[].name'); do
  tag=$(curl -s -u admin:$HARBOR "https://harbor.internal/api/v2.0/projects/myapp/repositories/$img/artifacts?tags=true" | jq -r '.[0].tags[0].name')
  cosign sign --yes "harbor.internal/$img:$tag"
  echo "Re-signed: $img:$tag"
done
```

### Сценарий 3: Откат при компрометации зависимости

```bash
# 1. Определение последней «хорошей» версии
# Проверка Rekor: когда последний раз артефакт был подписан валидно
rekor-cli search --artifact harbor.internal/my-app:v1.2.3 --format json

# 2. Проверка предыдущей версии
cosign verify harbor.internal/my-app:v1.2.2 \
  --certificate-identity-regexp "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer "https://harbor.internal"
# → Signature is valid

# 3. Проверка SBOM предыдущей версии
trivy image harbor.internal/my-app:v1.2.2 --severity CRITICAL
# → 0 vulnerabilities

# 4. Откат деплоя
kubectl rollout undo deployment/my-app -n production
# → deployment.apps/my-app rolled back

# 5. Фиксация отката в Git
git tag -a v1.2.2-rollback -m "Rollback to v1.2.2 due to $CVE in v1.2.3"
git push origin v1.2.2-rollback
```

### Сценарий 5: CI/CD pipeline compromise — emergency response для DevOps

Когда злоумышленник получает доступ к CI/CD runner или модифицирует pipeline-конфигурацию:

```bash
# 1. ОБНАРУЖЕНИЕ: подозрительный egress из CI runner
#    (Falco alert: "Launch of process in CI runner from unauthorized binary")
#    или: неожиданный docker pull в логах runner

# 2. Немедленная блокировка
# GitLab CI — emergency pause всех pipeline:
curl -s -X POST \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.internal/api/v4/projects/$PROJECT_ID/pipelines pause

# GitHub Actions — отключить workflow:
gh workflow disable ci-cd.yml

# Jenkins — безопасно остановить очередь:
curl -X POST "https://jenkins.internal/job/$JOB_NAME/safeStop"

# 3. Аудит изменений в pipeline config (Git history):
git log --oneline -10 .gitlab-ci.yml
# → ищем коммиты с подозрительными изменениями (curl|bash, base64-decoded secrets)
git log -p --all -S 'curl' -- .gitlab-ci.yml

# 4. Проверка всех артефактов, собранных за последние 24 часа:
for commit in $(git log --since="24 hours ago" --format='%H'); do
  tag=$(git tag --contains $commit | head -1)
  [ -n "$tag" ] && echo "Checking artifact for commit $commit → tag $tag"
  trivy image --vuln $CVE harbor.internal/$PROJECT_NAME:$tag 2>/dev/null
done

# 5. Ротация всех секретов, доступных CI runner:
# Kubernetes:
kubectl delete secret ci-runner-secrets --namespace gitlab-runner
# Vault:
vault kv rotate secret/data/ci-access-tokens/*
```

### Сценарий 4: Массовая проверка всех образов на конкретную CVE

```bash
# Скрипт массовой проверки (bash)
#!/bin/bash
CVE=$1
REGISTRY="harbor.internal"
PROJECT="myapp"
HARBOR_USER="admin"
HARBOR_PASS=$(kubectl get secret harbor-creds -o jsonpath='{.data.password}' | base64 -d)

echo "=== Audit for $CVE ==="

# Получение всех репозиториев
repos=$(curl -s -u "$HARBOR_USER:$HARBOR_PASS" \
  "https://$REGISTRY/api/v2.0/projects/$PROJECT/repositories" | jq -r '.[].name')

for repo in $repos; do
  # Получение последних 5 тегов
  tags=$(curl -s -u "$HARBOR_USER:$HARBOR_PASS" \
    "https://$REGISTRY/api/v2.0/projects/$PROJECT/repositories/$repo/artifacts?with_tag=true&n=5" \
    | jq -r '.[].tags[0].name')
  
  for tag in $tags; do
    result=$(trivy image --format json --vuln "$CVE" "$REGISTRY/$repo:$tag" 2>/dev/null | \
      jq -r '.Results[].Vulnerabilities[]?.VulnerabilityID // empty')
    
    if [ -n "$result" ]; then
      echo "[AFFECTED] $repo:$tag — $CVE found"
    else
      echo "[OK]       $repo:$tag — no $CVE"
    fi
  done
done
```

## Лучшие практики

1. **Готовые runbook:** Для каждого типа инцидента (уязвимость, компрометация ключа, подмена образа, CI/CD compromise) — отдельный runbook с командами и checklist.
2. **Automated rollback:** Настройте автоматический откат при обнаружении критичной CVE в продакшене (Argo Rollouts, Flux, или Kubernetes `kubectl rollout undo` через алерт-триггер).
3. **VEX для ложных срабатываний:** Не все CVE требуют реакции. Создавайте VEX с `not_affected` и `justification: vulnerable_code_not_present` для подтверждения non-reachability и фиксируйте решение.
4. **Проверка SBOM перед откатом:** Убедитесь, что откатная версия не содержит других уязвимостей. Сравните SBOM через `cyclonedx-cli diff`.
5. **Ротация ключей:** Периодическая (раз в 90 дней) ротация ключей подписи. При компрометации — немедленная, с проверкой всех артефактов в Rekor.
6. **Postmortem в течение 48 часов:** Blameless analysis с timeline, root cause и action items с владельцами и сроками.
7. **CI/CD isolation:** CI runner'ы работают в отдельной сети с egress control — только к доверенным реестрам и internal API. Блокируйте `0.0.0.0/0` egress.
8. **SBOM on every build:** Генерируйте и сохраняйте SBOM (Syft → Harbor OCI artifact) для каждого билда. Используйте как единственный источник truth для blast radius assessment.
9. **Immutable infrastructure:** Не выполняйте `apt-get install` или `pip install` на продакшен-серверах. Все изменения через rebuild + redeploy pipeline с подписью.
10. **Egress monitoring:** Sysadmin следит за egress traffic через eBPF (Falco/Tetragon). Alert на соединения к неизвестным IP вне allowlist.
11. **Dependency pinning:** Lock-файлы обязательны. Для bare-metal серверов используйте Nix или Ansible с зафиксированными хешами пакетов.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Откат не помог | Уязвимость есть в обеих версиях | Проверьте предыдущую версию: `trivy image --vuln CVE ...` |
| Нет «хорошей» версии | Все версии затронуты | Соберите новый образ с исправлением, проверьте SBOM |
| Kyverno блокирует откат | Политика требует подпись | Убедитесь, что откатная версия подписана валидным ключом |
| Rekor не возвращает записей | Артефакт не был подписан через keyless | Проверьте `--tlog-upload=true` при подписи |

## Граничные случаи и ограничения

* **Откат без подписи:** Если предыдущая версия не подписана, Kyverno может блокировать деплой. В emergency-режиме используйте `--validate=false` или временно снизьте политику на 30 минут.
* **Цепочка зависимостей:** Исправление одной зависимости может сломать другую. Всегда запускайте полный набор тестов после hotfix.
* **Время отката:** В Kubernetes откат занимает 30–60 секунд. Для критичных сервисов используйте blue-green deployment с предварительным переключением трафика.
* **Air-gapped среды:** При откате убедитесь, что образ предыдущей версии уже присутствует в локальном реестре. Для изолированных сред используйте Harbor Harbor-to-Harbor репликацию для предварительной загрузки образов.
* **Multi-architecture:** При откате на bare-metal убедитесь, что образ подходит для архитектуры серверов (amd64/arm64). Используйте `syft <image> -o json | jq '.manifest.mediaType'` для проверки архитектуры.

### SRE runbook: service degradation при supply chain incident

Инцидент цепочки поставок часто проявляется не как security breach, а как **service degradation** — рост latency, падение throughput, увеличение error rate. Приоритеты ответа меняются:

```yaml
# SLI/SLO для supply chain degradation:
# • API latency > 95th percentile baseline +20% → trigger alert
# • Error rate > 5% sustained for 5 min → trigger alert
# • New process spawns in already-deployed pod → immediate investigation
```

**Этап 1 — Stabilize (0–15 мин):**
```bash
# Идентифицировать подозрительные процессы через Falco
falco -K /var/run/secrets/kubernetes.io/serviceaccount/token \
  -r /etc/falco/rules.d/supply-chain-rules.yaml \
  --print -

# Emergency isolation affected pods
kubectl get pods -n production -l app=my-app \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | \
  xargs -I{} kubectl cordon {} 2>/dev/null || echo "not a node"
```

**Этап 2 — Diagnose (15–60 мин):**
```bash
# Проверить egress traffic к неизвестным IP
sysdig -pc 'fd.l4domain=inet and fd.type in (tcp) and (fd.sport != 443 and fd.sport != 80)' \
  --snaplen 512 --evtdev /dev/null | \
  jq -r '.proc.name, .fd.name' | \
  sort | uniq -c | sort -rn | head -20
```

**Этап 3 — Remediate (60+ мин):**
```bash
# Проверить SBOM текущего образа и сравнить с last-known-good
syft harbor.internal/my-app:v1.2.2 -o cyclonedx-json > /tmp/sbom-before.json
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > /tmp/sbom-after.json
cyclonedx-cli diff /tmp/sbom-before.json /tmp/sbom-after.json
# → показывает новые зависимости (потенциальный бэкдор)
```

### Sysadmin: bare-metal supply chain incident response

Для серверов в bare-metal или VM (без Kubernetes) типичны другие паттерны:

```bash
# 1. Обнаружение скомпрометированного процесса через eBPF
bpftool prog list | grep -i "supply_chain_monitor"
# Если программа не установлена — установите через:
# curl -sSL https://raw.githubusercontent.com/cilium/eBPF-Suite/main/install.sh | sh

# 2. Проверка целостости установленных пакетов (Debian/Ubuntu)
debsums -c | grep -E "CONFFILE|changed" | head -20
# → список изменённых конфигурационных файлов

# 3. Проверка хешей критичных бинарей
for bin in $(which python3 pip3 nginx); do
  echo "$bin: $(sha256sum $bin | cut -d' ' -f1)"
done
# → сравнить с эталонными хешами из инвентаря

# 4. Аудит загрузки динамических библиотек
lsof -p $(pgrep -f "my-app") | grep "\.so" | grep -v "/usr/lib"
# → библиотеки загруженные из нестандартных путей (подозрительно)

# 5. Анализ startup скриптов
grep -r "curl\|wget" /etc/init.d/ /etc/systemd/system/ /etc/rc.local 2>/dev/null
# → удалённые скрипты, загруженные через curl|bash
```

**Emergency playbook для bare-metal:**
```bash
# 1. Snapshot filesystem через LVM
lvcreate -L10G -s -n root-snapshot /dev/vg/root
# 2. Блокировать egress на уровне iptables
iptables -I OUTPUT -m owner ! --uid-owner 0 -j DROP
iptables -I OUTPUT -d harbor.internal -j ACCEPT
# 3. Открыть incident ticket с хешами всех бинарей
sha256sum $(which nginx python3 node) > /evidence/binary-hashes.txt
```

## Дополнительная информация

### Связанные документы

* [Реагирование на инциденты в Kubernetes](../../Kubernetes/Security/incident_response.md) — общий DFIR-процесс для K8s.
* [Целостности сборки](./build_integrity.md) — SLSA и верификация аттестаций.
* [Подпись артефакатов](./artifact_signing.md) — Cosign, Notation и ротация ключей.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз.
* [Примеры реальных атак на цепочку поставок](./supply_chain_attack_examples.md) — случаи компрометаций maintainer-аккаунтов, CI/CD и runtime.
