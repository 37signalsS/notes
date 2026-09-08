# Production Checklist для Deployment в Kubernetes

Чеклист проверок перед деплоем, во время деплоя и после деплоя в production-среду. Каждый пункт включает команды проверки и объяснение почему это важно.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.16+).
- Установленный `kubectl`, `kubeconform`, `trivy`.
- Доступ к кластеру с правами на проверку ресурсов.
- Базовое понимание [Deployment](./index.md) и [Лучших практик](./deployment_manifest.md).

## 1. Определения

**Production Checklist** — структурированный список проверок, выполняемых перед развертыванием изменений в production-среде. Цель — минимизировать риск инцидентов и обеспечить соответствие стандартам безопасности.

> Общие best practices для манифестов см. в [Deployment Best Practices](./deployment_manifest.md). Чеклисты по предотвращению ошибок: [PodEvicted](../../../Kubernetes/Troubleshooting/Common_Errors/PodEvicted/prevention.md), [CreateContainerConfigError](../../../Kubernetes/Troubleshooting/Common_Errors/CreateContainerConfigError/prevention.md).

## 2. Базовые концепции

### Три фазы проверки

| Фаза | Когда | Что проверяем |
|:-----|:------|:-------------|
| **Pre-deploy** | Перед `kubectl apply` | Манифест, образ, ресурсы, безопасность |
| **During deploy** | Во время rollout | Готовность подов, отсутствие ошибок |
| **Post-deploy** | После завершения rollout | Работоспособность, метрики, логи |

## 3. Практические сценарии

### Phase 1: Pre-deploy Checklist

#### 1.1. Валидация манифеста

```bash
# Синтаксическая проверка (клиентская)
kubectl apply -f deployment.yaml --dry-run=client

# Серверная валидация (полная проверка схемы + admission)
kubectl apply -f deployment.yaml --dry-run=server

# Валидация схемы без кластера (для CI/CD)
kubeconform -strict -summary -output json deployment.yaml

# Проверка差异 между текущим и желаемым состоянием
kubectl diff -f deployment.yaml
```

**Почему важно:** Невалидные манифесты могут привести к непредсказуемому поведению控制器а, зависанию rollout или нарушению политик безопасности.

#### 1.2. Проверка образа

```bash
# Проверка наличия образа в реестре
crane manifest my-registry.com/app:1.4.2

# Сканирование на CVE
trivy image --severity HIGH,CRITICAL my-registry.com/app:1.4.2

# Проверка подписи образа (Sigstore/Cosign)
cosign verify --key cosign.pub my-registry.com/app:1.4.2

# Проверка SBOM
trivy image --format cyclonedx --output sbom.json my-registry.com/app:1.4.2
```

**Почему важно:** Неподписанные или уязвимые образы — основной вектор атаки в supply chain.

#### 1.3. Проверка ресурсов

```bash
# Проверка квот в неймспейсе
kubectl describe quota -n production

# Проверка доступных ресурсов на узлах
kubectl top nodes

# Проверка текущего потребления
kubectl top pods -n production

# Проверка LimitRange
kubectl get limitrange -n production -o yaml
```

**Почему важно:** Нехватка ресурсов приведет к Pending подам и зависанию rollout. Превышение квоты заблокирует создание новых подов.

#### 1.4. Проверка безопасности

```bash
# Проверка PSA-лейблов на неймспейсе
kubectl get ns production -o jsonpath='{.metadata.labels}' | jq .

# Проверка SecurityContext в манифесте
yq '.spec.template.spec.securityContext' deployment.yaml

# Проверка NetworkPolicy
kubectl get networkpolicy -n production

# Проверка ServiceAccount
kubectl get sa -n production
```

#### 1.5. Проверка зависимостей

```bash
# Проверка существования ConfigMap/Secret
kubectl get configmap app-config -n production
kubectl get secret app-secrets -n production

# Проверка PDB
kubectl get pdb -n production

# Проверка Service и Endpoints
kubectl get svc -n production
```

### Phase 2: During-deploy Checklist

#### 2.1. Мониторинг rollout

```bash
# В отдельном терминале: мониторинг в реальном времени
kubectl rollout status deployment/my-app --timeout=5m

# Мониторинг подов
kubectl get pods -l app=my-app -w

# Мониторинг событий
kubectl get events -n production --sort-by='.lastTimestamp' -w
```

#### 2.2. Проверка здоровья подов

```bash
# Быстрая проверка статуса
kubectl get pods -l app=my-app -o wide

# Детальная проверка проблемных подов
kubectl describe pod <pod-name>

# Логи нового пода
kubectl logs <new-pod-name> --tail=50

# Проверка готовности
kubectl get endpoints -n production
```

#### 2.3. Проверка отсутствия regressions

```bash
# Проверка ошибок в логах
kubectl logs -l app=my-app --tail=100 | grep -i error

# Проверка метрик (если настроен Prometheus)
# error rate должен оставаться стабильным
# latency не должен увеличиваться

# Проверка активных соединений
kubectl exec -it <pod-name> -- ss -tlnp
```

### Phase 3: Post-deploy Checklist

#### 3.1. Финальная валидация

```bash
# Rollout завершен успешно?
kubectl rollout status deployment/my-app --timeout=1m

# Все поды Ready?
kubectl get pods -l app=my-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'

# Версия образа корректна?
kubectl get deployment my-app -o jsonpath='{.spec.template.spec.containers[0].image}'
```

#### 3.2. Проверка работоспособности

```bash
# Smoke-тесты
curl -s https://my-app.production.svc.cluster.local/healthz

# Проверка изнутри кластера
kubectl run test-pod --rm -it --image=curlimages/curl -- \
  curl -s http://my-app.production.svc.cluster.local/ready

# Проверка извне (через Ingress/Gateway)
curl -s https://my-app.example.com/healthz
```

#### 3.3. Проверка метрик

```bash
# Проверка алертов (Prometheus)
# Убедиться, что нет новых алертов

# Проверка Grafana dashboard
# Error rate, latency, throughput — все в норме

# Проверка SLO
# Error budget не исчерпан
```

#### 3.4. Документирование

```bash
# Зафиксировать причину изменения
kubectl annotate deployment/my-app \
  kubernetes.io/change-cause="Обновление до 1.4.2: CVE-2026-xxx"

# Проверить историю ревизий
kubectl rollout history deployment/my-app

# Убедиться, что change-cause заполнен
kubectl get deployment my-app -o jsonpath='{.metadata.annotations.kubernetes\.io/change-cause}'
```

### Автоматизация в CI/CD

```yaml
# Пример GitLab CI stages
stages:
  - validate
  - scan
  - deploy
  - verify

validate:
  stage: validate
  script:
    - kubeconform -strict -summary deployment.yaml
    - kubectl apply -f deployment.yaml --dry-run=server

scan:
  stage: scan
  script:
    - trivy image --severity HIGH,CRITICAL --exit-code 1 my-registry.com/app:$TAG

deploy:
  stage: deploy
  script:
    - kubectl apply -f deployment.yaml
    - kubectl annotate deployment/my-app kubernetes.io/change-cause="$CI_COMMIT_MESSAGE" --overwrite
  environment:
    name: production

verify:
  stage: verify
  script:
    - kubectl rollout status deployment/my-app --timeout=5m
    - |
      if ! kubectl rollout status deployment/my-app --timeout=5m; then
        echo "Rollout failed, rolling back"
        kubectl rollout undo deployment/my-app
        exit 1
      fi
  after_script:
    - kubectl get pods -l app=my-app -o wide
```

### Экстренные процедуры

```bash
# Откат к предыдущей версии
kubectl rollout undo deployment/my-app

# Откат к конкретной ревизии
kubectl rollout undo deployment/my-app --to-revision=2

# Экстренная остановка
kubectl scale deployment/my-app --replicas=0

# Принудительный перезапуск (применение конфига)
kubectl rollout restart deployment/my-app
```

### Частые ошибки и как их избежать

| Ошибка | Последствие | Как избежать |
|:-------|:-----------|:-------------|
| Нет readinessProbe | RollingUpdate удаляет старые поды до готовности новых | Всегда добавлять readinessProbe |
| Нет resources.requests | Планировщик не может разместить под | Всегда указывать requests |
| Нет resources.limits | Под может потребить все ресурсы узла | Всегда указывать limits |
| `:latest` тег | Невоспроизводимый деплой, сломанный откат | Использовать конкретные теги |
| Нет change-cause | История ревизий бесполезна для RCA | Всегда заполнять аннотацию |
| Нет preStop | 5xx при обновлении Endpoints | Добавлять preStop sleep |
| Нет terminationGracePeriodSeconds | Принудительное завершение соединений | Увеличивать для тяжелых приложений |

## 4. Дополнительная информация

### См. также
- [Манифест и лучшие практики](./deployment_manifest.md) — детальный разбор полей манифеста.
- [Устранение неполадок](./troubleshooting.md) — диагностика при сбоях.
- [Безопасность Deployment](./deployment_security_hardening.md) — hardened манифест.
- [CI/CD Integration](../../../CI-CD/ci_cd_overview.md) — общие принципы CI/CD.
- [Incident Response](../../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md) — реагирование на инциденты.
