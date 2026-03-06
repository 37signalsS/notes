# Операции kubeconform: офлайн, CRD, лучшие практики

## Определения

**Операции kubeconform** — офлайн-валидация, работа с CRD, настройка флагов и лучшие практики.

> **Навигация:** [Главная kubeconform](./index.md) | [Использование](./usage.md)

---

## Practical Scenarios

### Офлайн-валидация

**Загрузка схем для офлайн-работы:**

```bash
# Создание локального кэша схем
mkdir -p ~/kubeconform-schemas
kubeconform -list-schemas > schemas.txt

# Загрузка схем (скрипт)
while read schema; do
  curl -L "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/master/${schema}" \
    -o "~/kubeconform-schemas/${schema}"
done < schemas.txt
```

**Использование локальных схем:**

```bash
kubeconform -schema-location ~/kubeconform-schemas/{{ .ResourceKind }}.yaml manifests/
```

---

### Валидация CRD

**С указанием путей к схемам CRD:**

```bash
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' \
  manifests/
```

**С локальными CRD схемами:**

```bash
kubeconform \
  -schema-location default \
  -schema-location './crd-schemas/{{ .ResourceKind }}.json' \
  manifests/
```

---

### Строгая валидация

**Режим strict (запрет дополнительных полей):**

```bash
kubeconform -strict deployment.yaml
```

**С указанием версии Kubernetes:**

```bash
# Валидация против конкретной версии K8s
kubeconform -kubernetes-version 1.31.0 manifests/

# Валидация против master-ветки
kubeconform -kubernetes-version master manifests/
```

---

## Additional Information

### Флаги командной строки

| Флаг | Описание |
| :--- | :--- |
| `-R` | Рекурсивная проверка директорий |
| `-summary` | Вывод краткой сводки в конце |
| `-verbose` | Подробный вывод по каждому файлу |
| `-strict` | Строгий режим (запрет дополнительных полей) |
| `-output <format>` | Формат вывода (text, json, tap, junit) |
| `-kubernetes-version <ver>` | Версия Kubernetes для схем |
| `-schema-location <url>` | Путь к схемам (поддержка шаблонов) |
| `-ignore-missing-schemas` | Не ошибаться при отсутствии схем |
| `-skip-tls` | Пропускать проверку TLS для удалённых схем |
| `-cache <dir>` | Директория для кэширования схем |

---

### Сравнение с аналогами

| Инструмент | Производительность | CRD | Офлайн | CI/CD форматы |
| :--- | :--- | :--- | :--- | :--- |
| **kubeconform** | ⚡⚡⚡ | ✅ | ✅ | TAP, JUnit, JSON |
| **kubeval** | ⚡ | ❌ | ❌ | Text |
| **kube-linter** | ⚡⚡ | ✅ | ✅ | SARIF, JSON |

---

### Лучшие практики

1. **Интегрируйте в pre-commit хуки** для раннего обнаружения ошибок
2. **Используйте кэширование схем** для ускорения CI/CD
3. **Валидируйте против конкретной версии** Kubernetes вашего кластера
4. **Используйте strict режим** для предотвращения опечаток
5. **Настройте CRD схемы** для кастомных ресурсов

---

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes схемы | 1.20+ | Поддержка до 1.32+ |
| Go | 1.21+ | Для сборки из исходников |

---

### Связанные документы

- **[Kustomize](./kustomize_overview.md)** — валидация результатов kustomize
- **[Helm](./Helm/helm_overview.md)** — валидация Helm-чартов
- **[GitOps](../../../GitOps/GitOps_overview.md)** — интеграция в GitOps-пайплайны

### Репозиторий и документация

- [GitHub: yannh/kubeconform](https://github.com/yannh/kubeconform)
- [Схемы Kubernetes JSON](https://github.com/yannh/kubernetes-json-schema)
