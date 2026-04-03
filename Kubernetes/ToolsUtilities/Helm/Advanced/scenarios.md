# Сценарии Helm: репозитории, Kustomize, адаптивные шаблоны

## Определения

**Сценарии Helm** — практические случаи использования Helm для создания репозиториев, интеграции с Kustomize и создания адаптивных шаблонов.

## Базовые концепции

### Типы сценариев

Сценарии Helm охватывают три ключевые области:

1. **Публикация чартов** — создание и сопровождение Helm-репозиториев для распространения чартов
2. **Интеграция с Kustomize** — гибридный подход для разделения шаблонизации и конфигурации окружений
3. **Адаптивные шаблоны** — создание чартов, совместимых с разными версиями Kubernetes

### Когда применяются

- При подготовке чартов для многократного использования в разных кластерах
- При миграции с Kustomize на Helm или наоборот
- При поддержке чарта, работающего с несколькими версиями Kubernetes

> **Навигация:** [Главная Advanced](./index.md) | [Паттерны](./patterns_troubleshooting.md) | [Безопасность](./security_best_practices.md)

---

## Практические сценарии

### 1. Создание собственного репозитория

Helm-репозиторий — это HTTP-сервер, который отдает YAML-файл `index.yaml` и упакованные чарты (`.tgz`).

**Ключевые требования:**

1. HTTP-сервер, способный обслуживать файлы YAML и `.tgz` по GET-запросам.
2. Наличие файла `index.yaml`, который содержит метаданные обо всех чартах в репозитории.
3. Опционально: файлы `.prov` для верификации чартов.

**Рабочий процесс:**

1. **Упаковка чарта:** Создается `.tgz` архив из директории чарта.

    ```bash
    helm package ./my-chart
    ```

2. **Создание/обновление индекса:** Генерируется или обновляется `index.yaml` с информацией о чартах в текущей директории.

    ```bash
    helm repo index . --url https://my-repo.com/charts
    ```

3. **Публикация:** Архив `.tgz` и файл `index.yaml` загружаются на HTTP-сервер.

---

### 2. Гибридное использование с Kustomize

Для сложных проектов эффективен гибридный подход: **Helm** используется как шаблонизатор, а **[Kustomize](../../kustomize/kustomize_overview.md)** — для наложения патчей, специфичных для окружения.

**Структура проекта:**

```
k8s-project/
├── base/         # Базовые манифесты, сгенерированные `helm template`
├── overlays/     # Патчи для окружений (dev, prod)
└── helm/         # Исходный Helm-чарт
```

**Рабочий процесс:**

1. **Генерация базы:** `helm template` создает "сырые" Kubernetes-манифесты из чарта.

    ```bash
    helm template my-release ./helm > ./base/resources.yaml
    ```

2. **Применение патчей:** `kubectl apply -k` использует Kustomize для применения патчей к базовым манифестам перед отправкой в кластер.

    ```bash
    kubectl apply -k overlays/dev
    ```

Этот подход сочетает гибкость шаблонов Helm и декларативность патчей Kustomize, позволяя избежать сложной логики в чартах.

---

### 3. Создание адаптивных ("умных") шаблонов

Шаблоны Helm позволяют не просто вставлять значения, но и создавать логику, которая адаптирует манифесты под окружение, в частности, под версию Kubernetes. Это ключевой аспект создания по-настоящему переиспользуемых и надежных чартов.

#### Пример: Адаптивный Ingress-шаблон

Шаблон `ingress.yaml`, генерируемый командой `helm create`, является отличным примером "умного" шаблона. Он решает несколько проблем совместимости "из коробки".

**Адаптация `apiVersion`:**

API для Ingress менялся несколько раз (`extensions/v1beta1` → `networking.k8s.io/v1beta1` → `networking.k8s.io/v1`). Шаблон использует встроенный объект `.Capabilities` для выбора корректной версии API, поддерживаемой кластером.

```yaml
{{- $kubeVersion := .Capabilities.KubeVersion.Version -}}
{{- if semverCompare ">=1.19-0" $kubeVersion -}}
apiVersion: networking.k8s.io/v1
{{- else if semverCompare ">=1.14-0" $kubeVersion -}}
apiVersion: networking.k8s.io/v1beta1
{{- else -}}
apiVersion: extensions/v1beta1
{{- end }}
kind: Ingress
...
```

- `.Capabilities.KubeVersion.Version` получает семантическую версию Kubernetes.
- `semverCompare` сравнивает версии, позволяя выстроить логическую цепочку.

**Динамическое управление `ingressClassName`:**

До Kubernetes 1.18 класс ингресса указывался через аннотацию. Начиная с 1.18, появилось специальное поле `spec.ingressClassName`. Шаблон элегантно обрабатывает оба случая.

```yaml
...
metadata:
  annotations:
    {{- if and .Values.ingress.className (not (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version)) }}
    {{- if not (hasKey .Values.ingress.annotations "kubernetes.io/ingress.class") }}
    {{- $_ := set .Values.ingress.annotations "kubernetes.io/ingress.class" .Values.ingress.className}}
    {{- end }}
    {{- end }}
    {{- with .Values.ingress.annotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- if and .Values.ingress.className (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version) }}
  ingressClassName: {{ .Values.ingress.className }}
  {{- end }}
...
```

- **Логика для старых версий (K8s < 1.18):**
    1. Проверяется, что `ingress.className` задан и версия кластера < 1.18.
    2. `hasKey` проверяет, не задал ли пользователь аннотацию `kubernetes.io/ingress.class` вручную.
    3. Если нет, `set` динамически **добавляет** эту аннотацию в словарь `.Values.ingress.annotations` перед его рендерингом через `toYaml`.
- **Логика для новых версий (K8s >= 1.18):**
    1. Проверяется, что `ingress.className` задан и версия кластера >= 1.18.
    2. Если да, рендерится поле `ingressClassName` в спецификации.

**Манипуляция строками с `printf`:**

Иногда имя ресурса, на который нужно сослаться, отличается от имени релиза. Например, сервис может называться `my-release-svc`. Функция `printf` позволяет конструировать такие строки на лету.

```yaml
...
{{- $fullName := include "mychart.fullname" . -}}
{{- $svcPort := .Values.service.port -}}
{{- $svcName := printf "%s-svc" $fullName -}}

...
backend:
  service:
    name: {{ $svcName }}
    port:
      number: {{ $svcPort }}
...
```

Здесь переменной `$svcName` присваивается результат форматирования строки — к полному имени релиза добавляется суффикс `-svc`.

Эти техники позволяют создавать универсальные чарты, которые работают в разных окружениях без необходимости ручной правки.

---

## Дополнительная информация

### Связанные темы

- [Helm Overview](../helm_overview.md) — базовые концепции Helm
- [Helm Commands](../helm_commands_and_workflow.md) — руководство по командам
- [Kustomize](../../kustomize/kustomize_overview.md) — управление конфигурацией через патчи
