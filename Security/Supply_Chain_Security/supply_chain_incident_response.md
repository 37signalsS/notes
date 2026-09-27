# Реагирование на инциденты безопасности цепочки поставок

## Определения

* **Supply Chain Incident (Инцидент цепочки поставок):** Событие, при котором скомпрометирован один из компонентов жизненного цикла ПО: зависимость, базовый образ, инструмент сборки, ключ подписи или CI/CD-пайплайн. Типичные примеры — вредоносный код в обновлённой библиотеке, подмена Docker-образа, компрометация ключа Cosign.
* **Blast Radius (Радиус поражения):** Масштаб затронутых сервисов и сред. Определяется по графу зависимостей (SBOM) и топологии деплоя.
* **Rollback (Откат):** Возврат к предыдущейverified версии артефакта с подтвержденной целостностью (подпись + SBOM + VSA).
* **Key Compromise (Компрометация ключа):** Утечка приватного ключа подписи, позволяющая злоумышленнику подписывать вредоносные артефакты от имени организации.
* **Postmortem (Постмортем):** Анализ после инцидента без поиска виноватых (blameless), фокусирующийся на корневых причинах и мерах по предотвращению повторения.

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
grype harbor.internal/my-app:v1.2.3 --show-vulnerability-reachability | grep $CVE
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
  --certificate-identity "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer "https://harbor.internal"
# → ERROR: no matching signatures found

# 2. ЛОКАЛИЗАЦИЯ: Блокировка всех образов, подписанных этим ключом
# Проверка в Rekor, какие артефакты были подписаны
rekor-cli search --public-key cosign.pub --format json | jq '.[].UUID'
# → ["uuid1", "uuid2", "uuid3"]

# 3. ЛОКАЛИЗАЦИОНИЗАЦИЯ: Блокировка деплоя
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
  --certificate-identity "https://harbor.internal/project/my-app" \
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

### Сценарий 4: Быстрый аудит всех образов на конкретную CVE

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

1. **Готовые runbook:** Для каждого типа инцидента (уязвимость, компрометация ключа, подмена образа) — отдельный runbook с командами и checklist.
2. **Automated rollback:** Настройте автоматический откат при обнаружении критичной CVE в продакшене (Argo Rollouts, Flux).
3. **VEX для ложных срабатываний:** Не все CVE требуют реакции. Создавайте VEX для подтверждения `not_affected` и фиксируйте решение.
4. **Проверка SBOM перед откатом:** Убедитесь, что откатная версия не содержит других уязвимостей.
5. **Ротация ключей:** Периодическая (раз в 90 дней) ротация ключей подписи. При компрометации — немедленная.
6. **Postmortem в течение 48 часов:** Blameless analysis с timeline, root cause и action items.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Откат не помог | Уязвимость есть в обеих версиях | Проверьте предыдущую версию: `trivy image --vuln CVE ...` |
| Нет «хорошей» версии | Все версии затронуты | Соберите новый образ с исправлением, проверьте SBOM |
| Kyverno блокирует откат | Политика требует подпись | Убедитесь, что откатная версия подписана валидным ключом |
| Rekor не возвращает записей | Артефакт не был подписан через keyless | Проверьте `--tlog-upload=true` при подписи |

## Граничные случаи и ограничения

* **Откат без.signature:** Если предыдущая версия не подписана, Kyverno может блокировать деплой. В emergency-режиме используйте `--force` или временно снизьте политику.
* **Цепочка зависимостей:** Исправление одной зависимости может сломать другую. Всегда запускайте полный набор тестов после hotfix.
* **Время отката:** В Kubernetes откат занимает 30–60 секунд. Для критичных сервисов используйте blue-green déploiement.
* **Air-gapped среды:** При откате убедитесь, что образ предыдущей версии уже присутствует в локальном реестре.

## Дополнительная информация

### Связанные документы

* [Реагирование на инциденты в Kubernetes](../../Kubernetes/Security/incident_response.md) — общий DFIR-процесс для K8s.
* [Целостность сборки](./build_integrity.md) — SLSA и верификация аттестаций.
* [Подпись артефактов](./artifact_signing.md) — Cosign, Notation и ротация ключей.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз.
