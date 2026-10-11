# Harbor: Multi-arch артефакты (OCI image index)

**Актуально для:** Harbor 2.15.x (OCI image index поддерживается с Harbor 2.0), Docker Engine 29.x, Buildx v0.37.1, skopeo v1.24.1, cosign v3.x

## Определения

* **OCI Image Index**: Манифест верхнего уровня, ссылающийся на список манифестов для разных платформ (os/architecture). Docker manifest list — популярная реализация OCI image index.
* **Parent artifact**: OCI index, ссылающийся на дочерние артефакты. В Harbor parlance и index, и входящие в него манифесты — артефакты.
* **Child artifact**: Артефакт, на который ссылается OCI index (например, образ для linux/amd64). Принадлежит parent-артефакту.
* **Platform**: Платформа в index — `os` + `architecture` (например, `linux/amd64`, `linux/arm64`).
* **Image index в Harbor**: Harbor 2.0+ управляет index как артефактом: в списке артефактов репозитория index отмечен папкой-иконкой рядом с digest.

## Основные концепции

### Как Harbor хранит multi-arch

```text
docker push harbor.local/prod/my-app:v1.0   (multi-arch, buildx)
   │
   └─ OCI Image Index  sha256:<index-digest>   ← parent artifact (папка-иконка в UI)
        ├─ manifest linux/amd64  sha256:<amd64-digest>   ← child artifact
        └─ manifest linux/arm64  sha256:<arm64-digest>   ← child artifact
```

* **OCI-артефакт** (index): кликабелен в UI — раскрывается и показывает дочерние элементы (например, amd64/arm64).
* **Docker V2S2 manifest list**: в таблице артефактов архитектуры не отображаются — информация о платформах указана в разделе **Overview** артефакта.
* **Pull**: клиент выбирает платформу автоматически (`docker pull`), либо явно (`docker pull --platform linux/arm64`).

### Сканирование и безопасность multi-arch

* **Scan overview** агрегируется по index; отчёт сканирования доступен per-platform (у каждого child-артефакта свой отчёт).
* **Deployment Security** проверяет **вложенные артефакты** index — образ Redis для ARM проверяется отдельно от amd64, а не index целиком. Уязвимость в одной платформе блокирует pull всего index.
* **Подписи**: подписывать index по digest; Cosign/Notation-подписи хранятся как Referrers (Harbor 2.11+).

### Удаление multi-arch артефактов

* Child-артефакт, на который ссылается index, **нельзя удалить** — сначала удаляются все index-родители.
* При удалении index с 9 child-артефактами, из которых 1 используется другим index, удалятся только 9 (артефакт, на который есть вторая ссылка, остаётся).

## Практические сценарии

### Сценарий 1: Сборка и пуш multi-arch образа

```bash
# Сборка под две платформы и пуш в Harbor (buildx)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag harbor.corp.local/production/my-app:v1.2.0 \
  --push .
# → pushing layers for linux/amd64, linux/arm64
# → v1.2.0: digest: sha256:<index-digest> size: ...
```

Теория и все режимы buildx (билдеры, bake, аттестации) — в [docker_buildx.md](../../Dockerfile/docker_buildx.md).

### Сценарий 2: Инспекция multi-arch артефакта

```bash
# Локально: платформы в index
docker buildx imagetools inspect harbor.corp.local/production/my-app:v1.2.0
# → Name:      harbor.corp.local/production/my-app:v1.2.0
# → Manifest:  sha256:<index-digest>
# → Platforms: linux/amd64, linux/arm64

# Сырой index (манифест с платформами и digest-ами children)
skopeo inspect --raw docker://harbor.corp.local/production/my-app:v1.2.0 | jq '.manifests[] | .platform, .digest'

# Digest конкретной платформы
skopeo inspect --raw docker://harbor.corp.local/production/my-app:v1.2.0 | \
  jq -r '.manifests[] | select(.platform.architecture=="arm64") | .digest'
```

### Сценарий 3: Просмотр в Harbor UI

1. **Projects → production → my-app** — артефакт с папкой-иконкой рядом с digest — это index.
2. Клик по артефакту (OCI) — раскрытие дочерних элементов (amd64/arm64).
3. Для Docker V2S2 manifest list — раздел **Overview** артефакта содержит информацию о платформах.
4. Per-platform отчёт сканирования — в Overview каждого child-артефакта.

### Сценарий 4: Pull конкретной платформы

```bash
# Автоматический выбор платформы (совпадает с хостом)
docker pull harbor.corp.local/production/my-app:v1.2.0

# Явная платформа
docker pull --platform linux/arm64 harbor.corp.local/production/my-app:v1.2.0
# → v1.2.0: digest: sha256:<arm64-manifest-digest> size: ...

# По digest index (весь multi-arch)
docker pull harbor.corp.local/production/my-app@sha256:<index-digest>
```

### Сценарий 5: Deployment Security для multi-arch

1. Включите Deployment Security в проекте (порог severity — см. [security_policies.md](./security_policies.md)).
2. При pull index Harbor проверяет **каждый вложенный артефакт**.
3. Уязвимость выше порога в любой платформе → pull index отклонён.
4. Для диагностики — отчёт сканирования per-platform в UI.

### Сценарий 6: Репликация multi-arch

1. Репликация передаёт index **и** все child-артефакты по digest (см. [replication.md](./replication.md)).
2. В целевом реестре восстанавливается полная структура: index → children.
3. Репликация по расписанию (pull-based) — см. [replication.md, сценарий 3](./replication.md#сценарий-3-pull-based-репликация-по-расписанию).
4. **Проверка:** после репликации `skopeo inspect --raw` на целевом реестре должен показывать те же платформы, что и в источнике.

### Сценарий 7: CI/CD и K8s — деплой multi-arch

**CI/CD (GitHub Actions, пример):**
```yaml
- name: Build multi-arch image
  uses: docker/build-push-action@v6
  with:
    platforms: linux/amd64,linux/arm64
    push: true
    tags: |
      ${{ env.REGISTRY }}/${{ env.PROJECT }}/${{ env.APP }}:${{ env.VERSION }}
      ${{ env.REGISTRY }}/${{ env.PROJECT }}/${{ env.APP }}:latest
```

**Kubernetes — фиксация по digest index:**
```yaml
image: harbor.corp.local/production/my-app@sha256:<index-digest>
```

> **SRE-замечание:** при `imagePullPolicy: IfNotPresent` и теге (не digest) kubelet использует локальный кэш и не перетянет обновлённый index. Фиксируйте multi-arch по digest index — он гарантирует набор платформ. Подробнее — [image_versioning_and_tagging.md, сценарий 4](../image_versioning_and_tagging.md#сценарий-4-фиксация-версии-in-kubernetes).

### Сценарий 8: SRE — мониторинг и алерты для multi-arch

Метрики Harbor — в [operations.md, сценарий 2](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus). Алерты, специфичные для multi-arch:

```bash
# 1. Алерта: pull index без платформ (признак повреждения index)
# PromQL: sum(rate(harbor_artifact_pulled[5m])) == 0
# → сработает, если потребители перестали тянут multi-arch index

# 2. Алерта: рост ImagePullBackOff в кластере
# kubectl get pods -A -o wide | grep -i ImagePullBackOff
# → индикация, что манифест содержит старый registry или платформа отсутствует в index

# 3. Алерта: превышение квоты проекта при mass-push multi-arch
# harbor_project_quota_usage_byte > 0.9 * harbor_project_quota_byte
# → multi-arch index с 5+ платформами упирает в квоту; увеличьте лимит или чистите старые теги

# 4. Burn rate: темп ошибок относительно SLO registry
# Пример SLO: 99.9% успешных registry-запросов за 30 дней
# → error budget = 0.1% (≈ 43 минуты деградации в месяц)
#   burn rate > 1 означает, что при текущем уровне ошибок SLO на месяц будет violated
# Детали и формула — [operations.md, сценарий 6](./operations.md#сценарий-6-slo-sli-i-error-budget)
```

**Чек-лист перед cutover/массовым push multi-arch:**
- [ ] Алерты на `harbor_artifact_pulled == 0` (5m) — ловит отсутствие pull-активности.
- [ ] Алерты на `ImagePullBackOff` в кластере — ловит старые registry/platform в манифестах.
- [ ] Алерты на квоту проекта — ловит mass-push, превышающий лимит.
- [ ] Burn-rate алерты по SLO 99.9% — ловит деградацию registry.
- [ ] Проверка `skopeo inspect --raw` на целевом реестре — подтверждает наличие всех платформ.

### Сценарий 9: Retention и GC для multi-arch

1. **Retention Policy** помечает неиспользуемые артефакты (включая child-артефакты index) — подробно в [usage.md, сценарий 8](./usage.md#сценарий-8-управление-жизненным-циклом-retention-immutable).
2. **Garbage Collection (GC)** физически удаляет помеченные слои/манифесты — [usage.md, сценарий 10](./usage.md#сценарий-10-garbage-collection).
3. **SRE-замечание:** multi-arch index с 5+ платформами потребляет в разы больше места, чем mono-arch. Планируйте квоту и retention-правила так, чтобы старые платформы (например, `linux/386`, `linux/ppc64le`) регулярно удалялись.
4. **Перед GC — DRY RUN:** `docker exec -it harbor /harbor/soft/harbor/harbor-core garbagecollect --dry-run ...` — оцените объём удаления без реального удаления.

### Сценарий 10: Air-gapped и QEMU — сборка multi-arch в изолированной среде

**Air-gapped сеть:** нет доступа к публичным реестрам (Docker Hub, GitHub Packages) для pull образов QEMU и base-образов.

```bash
# 1. Зарегистрируйте QEMU (эмуляция arm64/s390x и др.)
docker run --privileged multiarch/qemu-user-static --reset -p yes
# → registers binfmt_misc для arm64, arm, s390x, ppc64le

# 2. Сборка multi-arch без доступа к Docker Hub (buildx)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag harbor.corp.local/production/my-app:v1.2.0 \
  --push .
```

> **SRE-замечание:** QEMU в 5–10 раз медленнее нативной сборки (подробности — в [docker_buildx.md](../../Dockerfile/docker_buildx.md#1-qemu-эмуляция)). Для production-пайплайнов предпочтительна кросс-компиляция (Go, Rust, C/C++) без QEMU. В air-gapped среде предварительно загрузите base-образы и бинарники QEMU в Harbor, чтобы сборка не падала при отсутствии доступа к Docker Hub.

## Валидация

```bash
# Index содержит обе платформы
skopeo inspect --raw docker://harbor.corp.local/production/my-app:v1.2.0 | \
  jq '[.manifests[].platform | .os+"/"+.architecture]'
# → ["linux/amd64","linux/arm64"]

# Pull обеих платформ прошёл
docker manifest inspect harbor.corp.local/production/my-app:v1.2.0 | jq '.manifests | length'
# → 2

# Scan overview артефакта доступен
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/production/repositories/my-app/artifacts?with_tag=true&with_scan_overview=true" | \
  jq '.[] | {digest, scan: .scan_overview}'
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `manifest unknown` при pull | Платформа отсутствует в index или index не пушился целиком | Проверьте `skopeo inspect --raw`; пушите index, а не отдельный манифест |
| В UI один артефакт без признаков платформ | Docker V2S2 manifest list (не OCI index) | Платформы — в разделе Overview артефакта; для раскрытия используйте OCI index |
| Deployment Security блокирует pull | Уязвимость в одной из платформ | Отчёт per-platform в UI; исправьте или добавьте CVE в allowlist |
| Сканирование index «не запускается» | Сканирование выполняется для child-артефактов | Проверьте отчёты дочерних артефактов, а не index |
| Child-артефакт не удаляется | На него ссылается OCI index | Сначала удалите index-родитель (и все остальные parents) |

## Граничные случаи

* **Proxy Cache и multi-arch**: при pull через proxy-cache проекта Harbor кэширует запрошенные платформы; известное ограничение — pull одной платформы через кэш не всегда создаёт полный multi-arch артефакт в кэше (обсуждение goharbor/harbor#20920). Для полного multi-arch в кэше пулите все нужные платформы.
* **Подпись**: подписывайте index по digest — подписи привязаны к манифесту; при пересборке index digest меняется.
* **Репликация**: реплицируется index вместе с child-артефактами (передача по digest); в целевом реестре восстанавливается полная структура.
* **Digest в манифестах деплоя**: используйте digest index — он гарантирует набор платформ, а не только одну.
* **Retention и GC**: multi-arch index с 5+ платформами потребляет в разы больше места, чем mono-arch. Планируйте квоту и retention-правила так, чтобы старые платформы (например, `linux/386`, `linux/ppc64le`) регулярно удалялись (подробно — [usage.md, сценарии 8–10](./usage.md#сценарий-8-управление-жизненным-циклом-retention-immutable)).
* **QEMU vs кросс-компиляция**: QEMU в 5–10 раз медленнее нативной сборки. Для production-пайплайнов предпочтительна кросс-компиляция (Go, Rust, C/C++) без QEMU (подробности — [docker_buildx.md, §1](../../Dockerfile/docker_buildx.md#1-qemu-эмуляция)).
* **Air-gapped**: предварительно загрузите base-образы и бинарники QEMU в Harbor, чтобы сборка не падала при отсутствии доступа к Docker Hub.

## Лучшие практики

* **Пушите index целиком** — `docker buildx build --push` формирует OCI image index, а не отдельный манифест. Отдельный манифест без index не отображается как multi-arch в Harbor.
* **Используйте `--preserve-digests`** при переносе multi-arch между реестрами — digest index гарантирует неизменность.
* **Проверяйте index `skopeo inspect --raw`** — не один манифест, иначе можно пропустить платформу.
* **Фиксируйте multi-arch по digest index** в K8s-манифестах — он гарантирует набор платформ; теги мутабельны.
* **Подписывайте index по digest** — подписи привязаны к манифесту; при пересборке index digest меняется (подробнее — [image_signature_and_verification.md](../../Docker_security/image_signature_and_verification.md#граничные-случаи-и-ограничения)).
* **Планируйте квоту и retention** под multi-arch: index с 5+ платформами потребляет в разы больше места.
* **Мониторьте после cutover/mass-push**: `harbor_artifact_pulled`, алерты на `ImagePullBackOff` в кластере (сценарий 8).
* **Пилот перед mass-push** — один multi-arch образ end-to-end: build → push → pull → verify.
* **Документируйте платформы**: инвентарь платформ, digest index, результаты верификации — пригодится для аудита и отката.

## Дополнительная информация

* Официальная документация: [Working with OCI Artifacts](https://goharbor.io/docs/2.15.0/working-with-projects/working-with-images/working-with-oci-artifacts/), [Deleting Artifacts](https://goharbor.io/docs/2.15.0/working-with-projects/working-with-images/deleting-artifact/).
* **Сборка multi-arch (buildx)** — [docker_buildx.md](../../Dockerfile/docker_buildx.md).
* **Перенос multi-arch между реестрами** — [diagnostics_transfer.md](../../Docker_fs/images/diagnostics_transfer.md).
* **Подписи multi-arch** — [image_signature_and_verification.md](../../Docker_security/image_signature_and_verification.md).
* **Deployment Security** — [security_policies.md](./security_policies.md).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — OCI 1.1 и Referrers API.
* **[Работа с Harbor](./usage.md)** — push/pull, digest.
* **[Репликация](./replication.md)** — репликация по digest.
* **[Вопросы на собеседованиях](./harbor_interview_qa.md)** — Q&A по Harbor.
