# kubeswitches operations

## Definitions

**kubeswitches operations** — безопасность, ограничения и рекомендации по эксплуатации инструмента kubeswitches.

---

## Basic Concepts

### Модель безопасности

kubeswitches хранит kubeconfig каждого кластера в отдельном файле. Это требует:

- **Защиты файлов:** Каждый `config` содержит чувствительные данные (токены, сертификаты)
- **Изоляции production:** Production-контексты требуют дополнительных мер (шифрование, менеджеры секретов)
- **Контроля доступа:** Ограничение прав на чтение директории контекстов

### Ограничения инструмента

| Ограничение | Описание |
| :--- | :--- |
| **Нет управления внутри одного файла** | Требует отдельной директории на кластер |
| **Копирование файлов** | Медленнее чем `kubectl config use-context` |
| **Отсутствие синхронизации** | Изменения в облачных kubeconfig не синхронизируются автоматически |

### Альтернативы

Для сравнения с другими инструментами переключения контекстов см. [index.md](./index.md).

---

## Practical Scenarios

### Защита файлов kubeconfig

```bash
chmod 600 ~/.kube/contexts/*/config
chmod 700 ~/.kube/contexts
```

### Изоляция production-контекстов

Production kubeconfig следует хранить на зашифрованных носителях или в менеджерах секретов (HashiCorp Vault, AWS Secrets Manager).

### Обновление credentials

При ротации credentials в облачных провайдерах (GKE, EKS, AKS) требуется вручную обновить файлы `config` в директориях контекстов:

```bash
# GKE
gcloud container clusters get-credentials cluster-name --zone zone
cp ~/.kube/config ~/.kube/contexts/gke-prod/config

# Yandex Cloud
yc managed-kubernetes cluster get-credentials --name cluster-name
cp ~/.kube/config ~/.kube/contexts/yandex-prod/config
```

---

## Additional Information

### Связанные документы

- **[kubeswitches index](./index.md)** — основные понятия и сравнение с альтернативами
- **[Использование](./usage.md)** — установка, настройка, команды
- **[kubeconfig](../../Operations/kubeconfig_and_connection.md)** — структура kubeconfig
