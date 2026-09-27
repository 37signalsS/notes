# Ошибки загрузки образов (Image Pull Errors): Лучшие практики

## Определения

В данном разделе представлены стратегические рекомендации по проектированию инфраструктуры, безопасности цепочки поставок (Supply Chain) и оптимизации рантаймов для минимизации ошибок и ускорения запуска приложений. Базовые термины приведены в разделе [Определения](./definitions.md).

---

## Основные концепции

### Стратегические направления оптимизации

Эффективная эксплуатация образов в продакшене базируется на принципах "Defense in Depth" и минимизации сетевых задержек.

| Категория | Рекомендация | Техническое обоснование |
| :--- | :--- | :--- |
| **Целостность** | Подпись образов (Cosign/Notation) | Гарантирует, что в кластер попадают только артефакты, прошедшие Quality Gates в CI. |
| **Доступность** | Локальный Pull-through Cache | Исключает зависимость от внешних Registry и Rate Limits (Docker Hub). |
| **Скорость** | Lazy Pulling (stargz/nydus) | Позволяет запустить контейнер до полной загрузки всех слоев (скачивание данных по требованию). |
| **Плотность** | Тюнинг Image Garbage Collection | Предотвращает `DiskPressure` и `Eviction` подов из-за переполнения кэша образов. |
| **Валидация** | Admission Control (Kyverno/OPA) | Блокировка недоверенных реестров и образов без подписей на этапе API. |

### Выбор политики imagePullPolicy

Правильный выбор политики напрямую влияет на стабильность и скорость масштабирования:

- **`IfNotPresent`**: Основной выбор для production. Использует локальный кэш, минимизируя трафик и время старта.
- **`Always`**: Рекомендуется для безопасности, если существует риск несанкционированной подмены образа в реестре под тем же тегом (хотя использование мутабельных тегов само по себе является антипаттерном).
- **Использование Digest**: Самая надежная практика — указание образа через `@sha256:...`. В этом случае политика `IfNotPresent` работает максимально эффективно и безопасно.

**Правило дефолтов kubelet (важно для миграции и CI/CD):**

| Тег в `image:` | Политика по умолчанию | Когда явно переопределять |
| :--- | :--- | :--- |
| `:latest` или тег отсутствует | `Always` | Если `IfNotPresent` — добиться воспроизводимости (иначе при перезапуске kubelet на узле без образа будет pull). |
| Конкретная версия (`:1.27.3`, `:v1.2.3`) | `IfNotPresent` | Если мутабельный репозиторий (один тег перезаписывается) — выставить `Always`. |
| Digest (`@sha256:...`) | `IfNotPresent` | Нет смысла менять. Digest иммутабельный, конфликт невозможен. |

Подробное описание алгоритма выбора kubelet и связанных ошибок — в разделе [Распространённые ошибки](./common_errors.md#политика-загрузки-imagepullpolicy-и-её-влияние-на-ошибки) и [Определения](./definitions.md#политики-загрузки-imagepullpolicy).

### Троттлинг pull-запросов на стороне kubelet

`kubelet` ограничивает частоту обращений к реестру параметрами `--registry-pull-qps` и `--registry-burst` — это **защита от перегрузки реестра и неконтролируемого расхода трафика**:

| Параметр | Дефолт | Назначение | Когда увеличивать |
| :--- | :--- | :--- | :--- |
| `--registry-pull-qps` | `5` | Средняя частота pull-запросов в секунду (на каждый реестр) | В кластерах с собственным высокопроизводительным реестром (Harbor) и большим количеством одновременных деплоев. |
| `--registry-burst` | `10` | Допустимый пик (burst) сверх QPS | Если HPA за минуту поднимает десятки подов — увеличить, иначе `kubectl rollout` будет стоять в очереди. |

**Алгоритм Back-off** при неудачных попытках pull: `10s → 20s → 40s → 80s → 160s → 300s` (cap 5 минут). Это **встроенная** защита, не путать с `--registry-pull-qps`. Счётчик сбрасывается после успешного pull или перезапуска kubelet.

**Проверка текущих настроек узла:**
```bash
# Получить параметры kubelet на узле
ssh node-01 'cat /var/lib/kubelet/config.yaml | grep -E "registryPullQPS|registryBurst"'
# → registryPullQPS: 5
# → registryBurst: 10
```

Подробный разбор последствий превышения лимитов и связь с Docker Hub rate limit — в [Распространённые ошибки → Сценарий 9](./common_errors.md#сценарий-9-лавина-pull-запросов-из-за-imagepullpolicy-always).

### Жизненный цикл imagePullSecrets и безопасная ротация

`imagePullSecrets` — это `Secret` типа `kubernetes.io/dockerconfigjson`, содержащий JSON в формате `~/.docker/config.json`. Подробный разбор формата и пример ошибок 401 — в [Распространённые ошибки → Сценарий 2](./common_errors.md#сценарий-2-ошибки-аутентификации-в-частных-реестрах-401-unauthorized) и [Определения](./definitions.md). Ниже — операционные рекомендации, выявленные практикой.

**Принципы управления секретами:**

| Принцип | Реализация | Что это предотвращает |
| :--- | :--- | :--- |
| Минимизация blast radius | Один `docker-registry` secret **на реестр**, не на приложение | Компрометация секрета одного приложения не затрагивает остальные. |
| Отвязка секрета от манифеста | Секреты монтируются через `ServiceAccount.imagePullSecrets` или `pod.spec.imagePullSecrets`, **не хранятся в Git** | Утечка через репозиторий, случайный коммит. |
| Ротация без downtime | Новая версия секрета под другим именем + обновление `imagePullSecrets` → старый секрет удаляется после успешного pull всех подов | Окно неработоспособности при истечении пароля. |
| Отдельный namespace для секретов | `kube-system` или `registry-secrets` namespace + RBAC только для SA | Произвольное чтение секретов из пода через уязвимости. |
| Аннотация даты последней ротации | `metadata.annotations["registry.rotation/rotated-at"]: "2026-09-01"` | Отслеживание устаревших секретов через аудит. |

**Сценарий безопасной ротации secret без простоя:**

```bash
# 1. Создать новый Secret рядом со старым (другой namespace или имя)
kubectl create secret docker-registry regcred-v2 \
  --docker-server=registry.internal.corp \
  --docker-username=robot-deploy \
  --docker-password="$NEW_PASSWORD" \
  --namespace=production

# 2. Добавить новый secret в ServiceAccount (kubelet использует оба; pull пройдёт через любой)
kubectl patch serviceaccount app-sa -n production -p '
{
  "imagePullSecrets": [
    {"name": "regcred-v1"},
    {"name": "regcred-v2"}
  ]
}'

# 3. Дождаться распространения SA (kubelet обновит поды в течение ~1 минуты)
sleep 90

# 4. Удалить старый secret
kubectl delete secret regcred-v1 -n production
```

**Почему два секрета одновременно:** kubelet перебирает все `imagePullSecrets` подряд для каждого контейнера. Наличие валидного секрета в списке гарантирует успешный pull, пока второй ротируется. Удалять старый следует **только** после того, как все поды успешно прошли pull с новым секретом.

---

## Практические сценарии

### Сценарий 1: Защита цепочки поставок через Cosign и Kyverno

Для гарантии того, что в кластере работают только проверенные образы, необходимо внедрить проверку подписей.

**1. Подпись в CI/CD (Cosign):**
```bash
cosign sign --key cosign.key my-registry.io/app:v1.2.3
```

**2. Проверка в кластере (Kyverno Policy):**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-image-signature
spec:
  rules:
    - name: verify-signature
      match:
        resources:
          kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["my-registry.io/*"]
          attestations:
            - predicateType: cosign.sigstore.dev/attestation/v1
```

### Сценарий 2: Оптимизация запуска через Prefetching образов

В больших кластерах или при автоскейлинге (HPA) задержка загрузки тяжелого образа может нарушить SLA.

**Методы префетчинга (предварительной загрузки):**
1. **DaemonSet Image Puller:** Запуск пода с нужным образом на всех узлах.
2. **Kube-image-keeper:** Специализированные контроллеры для управления локальным кэшем.
3. **P2P Дистрибуция (Dragonfly/Kraken):** Использование пиринговых сетей для раздачи слоев между узлами, минуя центральный реестр (критично при запуске 1000+ реплик одновременно).

### Сценарий 3: Настройка Image Garbage Collection (GC)

Для предотвращения ошибок `DiskPressure` настройте пороги очистки в `KubeletConfiguration`:

```yaml
# Настройка через файл конфигурации kubelet
imageGCHighThresholdPercent: 80  # Начать очистку при 80% заполнении
imageGCLowThresholdPercent: 70   # Очищать до тех пор, пока не станет 70%
imageMinimumGCAge: "2m"          # Не удалять образы, скачанные менее 2 минут назад
```
*ПРИМЕЧАНИЕ: Если диск с образами вынесен на отдельный раздел (рекомендуется), GC будет учитывать только его заполнение.*

### Сценарий 4: Ускорение старта через Lazy Pulling (stargz)

Технология позволяет контейнеру стартовать за секунды, скачивая только те файлы образа, которые необходимы для запуска процесса, в то время как остальные слои докачиваются в фоне.

**Настройка containerd для stargz:**
В `/etc/containerd/config.toml` необходимо включить плагин `proxy_plugins.stargz`:
```toml
[proxy_plugins]
  [proxy_plugins.stargz]
    type = "snapshot"
    address = "/run/containerd-stargz-grpc/containerd-stargz-grpc.sock"
```
*Требует установки `stargz-snapshotter` на узле.*

### Сценарий 5: Привязка imagePullSecrets к ServiceAccount (централизованная аутентификация)

Размещение секрета в `ServiceAccount.imagePullSecrets` вместо `pod.spec.imagePullSecrets` снижает дублирование и упрощает аудит.

**Сравнение подходов:**

| Подход | Где указывается | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Per-Pod** | `spec.imagePullSecrets` в каждом манифесте | Точечное переопределение | Дублирование по подам; забытый секрет = `ImagePullBackOff`. |
| **Per-ServiceAccount** (рекомендуется) | `ServiceAccount.imagePullSecrets` | Один источник; автоматически применяется ко всем подам SA; легко аудитить | Под с другим SA не получит секрет; нужен RBAC на изменение SA. |
| **Per-Namespace автоматически** (controller, например `kubernetes-reflector` или `reloader`) | Контроллер копирует секреты в namespace | Не нужно создавать секрет в каждом namespace вручную | Дополнительный компонент; eventual consistency. |

**Пример манифеста ServiceAccount с pull-секретом:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: production
imagePullSecrets:
  - name: regcred-prod
  - name: regcred-mirror
automountServiceAccountToken: false  # Если под не использует API сервера
```

**Аудит: кто какие секреты использует:**

```bash
# Список всех SA с pull-секретами в кластере
kubectl get sa -A -o json | \
  jq -r '.items[] | select(.imagePullSecrets) | "\(.metadata.namespace)/\(.metadata.name) -> \(.imagePullSecrets[].name)"' | sort
# → kube-system/default -> regcred-cluster
# → production/app-sa -> regcred-prod, regcred-mirror
```

### Сценарий 6: Локальный pull-through кэш (Harbor / Nexus) для предотвращения 429

Собственный registry с режимом `proxy-cache` решает две задачи одновременно: снимает зависимость от публичных rate limit и ускоряет pull за счёт локальной сети. Подробный разбор настройки и конфигурации `hosts.toml` — в [Распространённые ошибки → Сценарий 11](./common_errors.md#сценарий-11-локальный-pull-through-кэш-harbornexus-для-on-prem).

**Когда внедрять:**

- Кластер > 50 узлов или > 200 одновременных pull.
- Прямой трафик до Docker Hub / GHCR / Quay превышает 100 GB/месяц.
- Сценарии auto-scaling (HPA) или node autoscaling с деплоем "с нуля".
- Воздушный зазор или строгие политики egress (свой реестр + proxy cache — единственный канал).

**Ожидаемый эффект (из опыта внедрения в on-prem кластерах):**

| Метрика | Без pull-through | С Harbor proxy cache |
| :--- | :--- | :--- |
| Время первого pull образа 1 GB на 100 узлах | 15–30 минут (rate limit) | 2–5 минут (после прогрева) |
| Исходящий трафик к Docker Hub | Полный объём слоёв | После прогрева — дельта новых слоёв |
| Инциденты `429 Too Many Requests` | Регулярно при rollout | Исключены для запрошенных ранее образов |

### Сценарий 7: Настройка HTTP/HTTPS прокси для узлов в on-prem сети

В корпоративных on-prem средах с обязательным egress через прокси (Squid, Nginx) настройка выполняется на уровне `containerd` и `kubelet`. Принципы, переменные окружения и порядок действий — в [Распространённые ошибки → Сценарий 12](./common_errors.md#сценарий-12-http-прокси-с-аутентификацией-squid).

**Чек-лист для DevOps/SRE:**

- [ ] Создан отдельный Service Account в прокси для кластера (не использовать личные учётки).
- [ ] NO_PROXY содержит: `127.0.0.0/8`, `10.0.0.0/8` (Pod CIDR), `172.16.0.0/12` (если Service CIDR), `192.168.0.0/16`, `.cluster.local`, `.svc`, Service CIDR кластера (по умолчанию `10.96.0.0/12`).
- [ ] HTTPS-прокси поддерживает `CONNECT` к портам 443 и 5000 (для незащищённых реестров).
- [ ] TLS-инспекция на прокси добавляет корпоративный CA в `/etc/containerd/certs.d/*/ca.crt` и `/etc/ssl/certs/ca-certificates.crt` на каждом узле.
- [ ] `systemctl edit containerd` прописал `Environment="HTTP_PROXY=..."` — без этого переменные не наследуются.
- [ ] Smoke-test: `crictl pull gcr.io/distroless/static:nonroot` с проблемного узла завершается за разумное время.

### Сценарий 8: Мониторинг и метрики pull-операций

Без мониторинга первая индикация проблемы — жалобы пользователей. Следующие метрики дают **proactive visibility** на этапы pull, GC и кэширования.

**Источники метрик:**

| Источник | Метрика | Что показывает |
| :--- | :--- | :--- |
| `kubelet` (`/metrics`) | `kubelet_image_pull_duration_seconds` (histogram) | Время pull одного образа. Алерт p95 > 60s. |
| `kubelet` | `kubelet_image_pull_errors_total{error_type}` | Рост ошибок (manifest, network, auth). |
| `kubelet` | `kubelet_image_garbage_collected_total` | Сколько образов удалено GC. |
| `kubelet` | `kubelet_image_gc_duration_seconds` | Длительность GC (резкий рост — давление на диск). |
| containerd (`/metrics`) | `containerd_image_pull_duration_seconds` | То же на уровне рантайма. |
| containerd | `containerd_image_pull_bytes_total` | Объём скачанных данных по слоям. |
| Реестр (Harbor/Prometheus) | `harbor_project_repo_artifact_pull_count` | Популярные образы, планирование ёмкости cache. |

**Пример Prometheus-алерта (время pull):**

```yaml
groups:
  - name: kubelet-image-pull
    rules:
      - alert: KubeletImagePullLatencyHigh
        expr: |
          histogram_quantile(0.95,
            sum by (instance, le) (kubelet_image_pull_duration_seconds_bucket)
          ) > 60
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "p95 pull latency > 60s на узле {{ $labels.instance }}"

      - alert: KubeletImagePullErrorsSpike
        expr: |
          rate(kubelet_image_pull_errors_total[10m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Рост ошибок pull на {{ $labels.instance }}: {{ $labels.error_type }}"
```

**Что мониторить в логах kubelet:**

```bash
# Фильтр событий pull для анализа трендов
journalctl -u kubelet --since "24 hours ago" | \
  grep -E "(Pulling|Pulled|Failed to pull|ImagePullBackOff)" | \
  awk '{print $1, $2, $3, $NF}' | sort | uniq -c | sort -rn | head
```

### Сводная таблица антипаттернов

| Антипаттерн | Чем опасен | Корректная практика | Раздел с деталями |
| :--- | :--- | :--- | :--- |
| `image: myapp:latest` в production | Непредсказуемая версия, ловит `429` при каждом rollout | `image: myapp:1.2.3@sha256:...` + `IfNotPresent` | [Сценарий 9 в common_errors](./common_errors.md#сценарий-9-лавина-pull-запросов-из-за-imagepullpolicy-always) |
| `imagePullPolicy: Always` + 100+ реплик | Превышение rate limit registry, медленный rollout | `IfNotPresent` + digest, либо pull-through cache | [Сценарий 9 в common_errors](./common_errors.md#сценарий-9-лавина-pull-запросов-из-за-imagepullpolicy-always) |
| `imagePullSecrets` в манифесте пода | Дублирование, риск утечки в Git | `ServiceAccount.imagePullSecrets` | [Сценарий 5](#сценарий-5-привязка-imagepullsecrets-к-serviceaccount-централизованная-аутентификация) |
| Один `imagePullSecrets` для всех приложений и всех реестров | При компрометации — компрометация всех сред | Отдельный secret на реестр + namespace | [Жизненный цикл](#жизненный-цикл-imagepullsecrets-и-безопасная-ротация) |
| Хранение пароля в `docker-registry` > 1 года | Почти гарантированная утечка/истечение | Ротация по расписанию (например, 90 дней) | [Ротация](#жизненный-цикл-imagepullsecrets-и-безопасная-ротация) |
| `imagePullPolicy: Never` без предзагрузки | Гарантированный `ImagePullBackOff` на новых узлах | DaemonSet Image Puller или `ctr image import` | [airgapped.md](./airgapped.md#сценарий-6-префетчинг-образов-через-daemonset) |
| Прямой pull из Docker Hub без аутентификации из on-prem | 100 pulls/6h на IP → `429`, остановка деплоев | Аккаунт + token, либо pull-through cache | [Сценарий 6](#сценарий-6-локальный-pull-through-кэш-harbor--nexus-для-предотвращения-429) |
| `--registry-pull-qps=0` (без троттлинга) | Перегрузка registry, каскадные сбои | Оставить дефолт `5`, увеличивать осознанно | [Троттлинг](#троттлинг-pull-запросов-на-стороне-kubelet) |
| `imageGCHighThresholdPercent: 95` (агрессивно) | Редкий GC → `DiskPressure` → Eviction | `85` / `80` (hysteresis 5%) | [Сценарий 3](#сценарий-3-настройка-image-garbage-collection-gc) |
| `imageGCHighThresholdPercent: 50` (слишком жадно) | Постоянное удаление слоёв → повторный pull на каждом узле | `85` / `80` | [Сценарий 3](#сценарий-3-настройка-image-garbage-collection-gc) |
| Image с одним слоем 4+ GB (`fat-jar`, `node_modules` в слое) | Долгий pull, частые cache misses | Multi-stage build, вынос статики в init-container | [Подпись и многоэтапная сборка](../../../../Security/Supply_Chain_Security/build_integrity.md) |
| Pull из публичного registry через корпоративный прокси без `NO_PROXY` для Service CIDR | Внутренние запросы уходят наружу → латентность + ложные `403` | Прописать `10.96.0.0/12`, `.cluster.local`, Pod CIDR | [Сценарий 7](#сценарий-7-настройка-httphttps-прокси-для-узлов-в-on-prem-сети) |
| Отключение admission controller при срабатывании | Открытый вектор для недоверенных образов | Kyverno/ImagePolicyWebhook с whitelist | [Сценарий 13 в common_errors](./common_errors.md#сценарий-13-admission-controller-блокирует-pull-kyvernoimagepolicywebhook) |

---

## Дополнительная информация

### Связанные темы

- [Пошаговая диагностика](./diagnostics.md) — алгоритм действий при возникновении сбоев.
- [Распространённые ошибки](./common_errors.md) — разбор типовых кодов ответа реестров (401, 403, 429).
- [Air-gapped кластеры](./airgapped.md) — специфика работы в полностью изолированных сетях.
- [NetworkPolicy и доступ к реестру](./network_policy_impact.md) — влияние NetworkPolicy и GlobalNetworkPolicy на image pull.
- [Pod Security Standards и image pull](./pod_security_standards.md) — PSS/PSA и их влияние на загрузку образов.
- [HPA и автоскейлинг](./hpa_and_scaling.md) — влияние масштабирования на image pull и rate limiting.
- [Init-контейнеры и image pull](./init_container_image_pulls.md) — проблемы pull в init-контейнерах.
- [Подпись артефактов](../../../../Security/Supply_Chain_Security/artifact_signing.md) — детальное руководство по Cosign и Notation.
- [Сканирование уязвимостей](../../../../Docker/Docker_security/vulnerability_scanning.md) — внедрение Trivy и Grype в пайплайны.

