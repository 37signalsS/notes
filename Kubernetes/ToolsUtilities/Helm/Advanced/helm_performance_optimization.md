# Оптимизация производительности Helm

Практические методы ускорения рендеринга, снижения нагрузки на API-сервер и эффективного управления большими чартами в продакшен-средах.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Template Rendering Time** | Время выполнения двухпроходного цикла рендеринга Helm: парсинг AST → подстановка значений → сериализация YAML. Зависит от количества шаблонов, сложности выражений и размера `values.yaml`. |
| **Release Storage Overhead** | Объём Secret-объектов в namespace `kube-system`, хранящих историю релизов (метаданные + манифесты предыдущих ревизий). Управляется флагом `--history-max`. |
| **Parallelism Gap** | Отсутствие нативного параллельного рендеринга в Helm: все шаблоны обрабатываются последовательно, что создаёт узкое место для чартов с hundreds of templates. |
| **Dependency Resolution Cost** | Время загрузки и объединения зависимостей (`helm dependency update`). Для чартов с десятками зависимостей из OCI-реестров может занимать 30–120 секунд в CI. |

---

## Теория

### Где тратится время при `helm install` / `helm upgrade`

| Этап | Описание | Типичная доля |
|------|----------|---------------|
| 1. Зависимости | `dependency build` / `update` — загрузка subcharts из репозитория | 10–40% (сетевой I/O) |
| 2. Рендеринг шаблонов | Парсинг Go templates, вычисление выражений, подстановка `.Values` | 5–15% |
| 3. Отправка в API-сервер | Серверный dry-run, проверка admission, запись в etcd | 40–70% (сеть + etcd) |
| 4. Ожидание готовности | `--wait` / `--wait-for-jobs` — polling статусов ресурсов | 0–90% (зависит от приложения) |

**Ключевой инсайт:** В 80% случаев узкое место — это сеть и API-сервер, а не рендеринг. Оптимизация шаблонов даёт marginal gain, если основное время тратится на Apply.

### Факторы, влияющие на скорость рендеринга

| Фактор | Влияние | Решение |
|--------|---------|---------|
| Количество файлов в `templates/` | Линейный рост времени парсинга | Группировка Related ресурсов в один файл через `---` |
| Сложность `tpl`-выражений | Каждый `tpl` вызывает повторный парсинг строки | Минимизация `tpl`, использование `include` |
| Размер `values.yaml` | Время deep merge при наличии множества `-f` файлов | Компактные values, `--set` для scalar overrides |
| Количество зависимостей | Каждый subchart — отдельный цикл рендеринга | Library charts вместо deep dependency trees |

---

## Практика

### 1. Оптимизация storage overhead релизов

По умолчанию Helm хранит все предыдущие ревизии релизов как Secret-объекты. Для чартов с большими манифестами ( hundreds of resources) это может превысить лимит etcd.

```bash
# Ограничить историю до 5 ревизий
helm install my-app ./my-chart \
  --history-max 5 \
  --atomic --wait --timeout 10m

# Проверить текущий storage overhead
kubectl get secrets -n kube-system -l owner=helm \
  -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.labels.created}{"\n"}{end}' | \
  sort -t: -k2 | tail -20

# Оценить общий объём
kubectl get secrets -n kube-system -l owner=helm -o json | \
  jq '[.items | .[].data | to_entries[] | .value | length] | add / 1024 | . + " KB"'
```

**Production-рекомендация:** `--history-max 10` для критичных сервисов (нужна глубина отката), `--history-max 3` для dev/staging.

### 2. Ускорение зависимостей в CI

```bash
# Кэширование зависимостей в CI (GitLab CI пример)
.cache_helm_deps: &cache_helm_deps
  cache:
    key: helm-deps-$CI_COMMIT_REF_SLUG
    paths:
      - .helmcache/

# Использование lock-файла для детерминизма
helm dependency build --skip-refresh ./my-chart  # без обновления индексов

# Локальный OCI-кэш (on-prem)
export HELM_REGISTRY_CONFIG=$HOME/.config/helm/registry/config.json
helm pull oci://harbor.internal/library/my-dep --version 1.2.3 -d .helmcache/
```

### 3. Параллелизм через внешние оркестраторы

Helm не поддерживает параллельный рендеринг/деплой. Для управления сотнями релизов:

**Helmwave:**
```yaml
# helmwave.yml
packages:
  - name: app-1
    chart: ./charts/app
    values: [values/app-1.yml]
  - name: app-2
    chart: ./charts/app
    values: [values/app-2.yml]
    needs: [app-1]  # DAG: app-2 после app-1

plan:
  parallel: true  # параллельный рендеринг
  kick_on_fail: true
```

**Helmfile:**
```yaml
# helmfile.yaml
releases:
  - name: app-1
    chart: ./charts/app
  - name: app-2
    chart: ./charts/app
    needs: [app-1]

helm: flags: --parallel
```

### 4. Оптимизация шаблонов

**Группировка ресурсов в один файл:**
```yaml
# templates/combined.yaml (вместо отдельных файлов)
{{- range .Values.components }}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .name }}-config
data:
  {{ .key }}: {{ .value }}
{{- end }}
```

**Кэширование результатов `include`:**
```yaml
# Вместо повторных вызовов include
{{- $fullname := include "mychart.fullname" . -}}
{{- $labels := include "mychart.labels" . -}}

spec:
  selector:
    {{- $labels | nindent 4 }}
  template:
    metadata:
      labels:
        {{- $labels | nindent 8 }}
    spec:
      containers:
        - name: {{ $fullname }}
```

**Минимизация `tpl`:**
```yaml
# ПЛОХО: tpl вызывается на каждой итерации
{{- range .Values.envVars }}
  - name: {{ .name }}
    value: {{ tpl .value $ | quote }}
{{- end }}

# ХОРОШО: предвычисление
{{- $values := dict "Values" .Values "Release" .Release -}}
{{- range .Values.envVars }}
  - name: {{ .name }}
    value: {{ .value | quote }}
{{- end }}
```

### 5. Оптимизация для `helm template` в CI

```bash
# Только рендеринг без API-запросов (мгновенно)
helm template my-release ./my-chart \
  -f values-prod.yaml \
  --dry-run=none \
  --debug 2>/dev/null | wc -l  # подсчёт манифестов

# Валидация без кластера (kubeconform — offline)
helm template my-release ./my-chart | kubeconform \
  -strict \
  -ignore-missing-schemas \
  -kubernetes-version 1.30.0

# Параллельный lint нескольких чартов
find ./charts/ -name Chart.yaml -exec dirname {} \; | \
  xargs -P4 -I{} helm lint --strict {}
```

### 6. Мониторинг производительности Helm

```bash
# Измерение времени рендеринга
time helm template my-release ./my-chart -f values-prod.yaml > /dev/null

# Сравнение версий чарта
for v in 1.0.0 1.1.0 1.2.0; do
  echo -n "v$v: "
  time helm template my-release ./my-chart --version $v > /dev/null 2>&1
done

# Метрики для Prometheus (через custom script)
cat <<'EOF' > /tmp/helm_metrics.sh
#!/bin/bash
CHART=$1
START=$(date +%s%N)
helm template test-release "$CHART" > /dev/null 2>&1
END=$(date +%s%N)
DURATION=$(( (END - START) / 1000000 ))
echo "helm_render_duration_ms{chart=\"$CHART\"} $DURATION"
EOF
```

---

## Антипаттерны

| Антипаттерн | Проблема | Решение |
|-------------|----------|---------|
| Отсутствие `--history-max` | etcd переполняется Secret-ревизиями релизов | Всегда задавайте `--history-max` |
| Монолитный umbrella chart на 50+ сервисов | Одна ошибка в шаблоне ломает все сервисы | Разделяйте на independent releases + umbrella для orchestration |
| `helm upgrade` без `--wait` в CI | Релиз помечен как successful до готовности подов | Используйте `--atomic --wait --wait-for-jobs` |
| Хранение всех values в одном файле | Slow merge при большом количестве override | Values layering: base → env → cluster → runtime |
| Повторное `helm dependency update` в каждом CI job | Сетевой I/O дублируется | Кэширование через CI cache + `--skip-refresh` |

---

## Дополнительная информация

- **[Паттерны и устранение неисправностей](./patterns_troubleshooting.md)** — атомарный деплой, SSA, values layering.
- **[Юнит-тестирование](./unit_testing.md)** — быстрая валидация шаблонов без кластера.
- **[Helmfile](../helmfile_overview.md)** — декларативная оркестрация с поддержкой parallel.
- **[Helmwave](../helmwave_overview.md)** — DAG-оркестрация с параллельным рендерингом.
- **[Helm CLI: --history-max](https://helm.sh/docs/helm/helm_install/)** — официальная документация по ограничению истории.
