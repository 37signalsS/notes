# kubeconform operations

## Definitions

**Операции kubeconform** — расширенные сценарии: офлайн-валидация, работа с CRD, строгий режим, настройка флагов.

---

## Basic Concepts

### Флаги командной строки

| Флаг | Описание |
| :--- | :--- |
| `-R` | Рекурсивная проверка директорий |
| `-summary` | Краткая сводка в конце вывода |
| `-verbose` | Подробный вывод по каждому файлу |
| `-strict` | Запрет дополнительных полей в манифестах |
| `-output <format>` | Формат: text, json, tap, junit |
| `-kubernetes-version <ver>` | Версия K8s для схем (например, `1.31.0`, `master`) |
| `-schema-location <url>` | Путь к схемам с поддержкой шаблонов `{{ .ResourceKind }}` |
| `-ignore-missing-schemas` | Пропуск ресурсов без схем |
| `-skip-tls` | Отключение проверки TLS для удалённых схем |
| `-cache <dir>` | Директория кэширования схем |

### Сравнение с аналогами

| Инструмент | Производительность | CRD | Офлайн | CI/CD форматы |
| :--- | :--- | :--- | :--- | :--- |
| **kubeconform** | Высокая (Go, параллелизм) | Да | Да | TAP, JUnit, JSON |
| **kubeval** | Низкая | Нет | Нет | Text |
| **kube-linter** | Средняя | Да | Да | SARIF, JSON |

---

## Practical Scenarios

### Офлайн-валидация

**Подготовка локального кэша схем:**

```bash
mkdir -p ~/kubeconform-schemas
kubeconform -list-schemas > schemas.txt

while read schema; do
  curl -L "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/master/${schema}" \
    -o "~/kubeconform-schemas/${schema}"
done < schemas.txt
```

**Использование:**

```bash
kubeconform -schema-location '~/kubeconform-schemas/{{ .ResourceKind }}.yaml' manifests/
```

### Валидация CRD

**Удалённые схемы (datree CRDs catalog):**

```bash
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' \
  manifests/
```

**Локальные CRD-схемы:**

```bash
kubeconform \
  -schema-location default \
  -schema-location './crd-schemas/{{ .ResourceKind }}.json' \
  manifests/
```

### Строгая валидация

**Режим strict (отклонение неизвестных полей):**

```bash
kubeconform -strict deployment.yaml
```

**Против конкретной версии K8s:**

```bash
kubeconform -kubernetes-version 1.31.0 manifests/
kubeconform -kubernetes-version master manifests/
```

---

## Additional Information

### Лучшие практики

1. Интеграция в pre-commit хуки для раннего обнаружения ошибок.
2. Кэширование схем для ускорения CI/CD.
3. Валидация против версии K8s целевого кластера.
4. Использование `-strict` для предотвращения опечаток.
5. Настройка `-schema-location` для CRD.

### Связанные документы

- [Главная kubeconform](./index.md)
- [Использование kubeconform](./usage.md)
- [Kustomize](../kustomize/kustomize_overview.md) — валидация результатов `kubectl kustomize`
- [Helm](../../ToolsUtilities/Helm/helm_overview.md) — валидация отрендеренных чартов
