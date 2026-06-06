# Администрирование Cert-manager

## Определения

**Администрирование cert-manager** — управление жизненным циклом сертификатов, диагностика, мониторинг и обеспечение безопасности.

## Основные концепции

### Управление секретами при удалении сертификатов

#### Поведение по умолчанию

По умолчанию cert-manager **не удаляет** Kubernetes `Secret` при удалении ресурса `Certificate`. Это сделано для безопасности — случайное удаление `Certificate` не должно приводить к потере рабочего TLS-сертификата.

**Проблема:** При пересоздании `Certificate` с тем же `secretName` cert-manager не обновляет существующий Secret, что может привести к использованию устаревшего сертификата.

#### Включение garbage collection

Для автоматического удаления Secret при удалении Certificate используйте флаг `--enable-certificate-owner-ref=true`.

**Helm:**

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set "extraArgs={--enable-certificate-owner-ref=true}"
```

**Поведение после включения:**

- cert-manager добавляет `ownerReference` к Secret, указывая на Certificate
- При удалении Certificate сборщик мусора Kubernetes автоматически удаляет Secret

| Преимущества | Риски |
| :--- | :--- |
| Упрощает управление жизненным циклом | Случайное удаление Certificate удаляет Secret |
| Автоматическая очистка | Возможны простои при ошибке |
| Прозрачная связь ресурсов | Требует осторожности в production |

> **Рекомендация:** Используйте с осторожностью в production. Включайте в development/staging.

## Practical Scenarios

### Сценарий: Включение garbage collection в существующем кластере

1. Проверьте текущие флаги контроллера:

   ```bash
   kubectl get deployment cert-manager -n cert-manager -o jsonpath='{.spec.template.spec.containers[0].args}'
   ```

2. Если флаг `--enable-certificate-owner-ref` отсутствует, добавьте его:

   ```bash
   helm upgrade cert-manager jetstack/cert-manager \
     --namespace cert-manager \
     --reuse-values \
     --set "extraArgs={--enable-certificate-owner-ref=true}"
   ```

3. Убедитесь, что поды перезапустились:

   ```bash
   kubectl rollout status deployment/cert-manager -n cert-manager
   ```

4. Проверьте, что `ownerReference` добавлен к существующим Secret:

   ```bash
   kubectl get secret <tls-secret> -n <namespace> -o jsonpath='{.metadata.ownerReferences}'
   ```

### Сценарий: Безопасное удаление Certificate с сохранением Secret

Если garbage collection **не включён** и нужно удалить `Certificate`, сохранив Secret:

1. Убедитесь, что Secret существует и содержит актуальный сертификат:

   ```bash
   kubectl get secret <tls-secret> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
   ```

2. Удалите ресурс Certificate:

   ```bash
   kubectl delete certificate <name> -n <namespace>
   ```

3. Проверьте, что Secret остался на месте:

   ```bash
   kubectl get secret <tls-secret> -n <namespace>
   ```

### Сценарий: Восстановление после случайного удаления Certificate

При включённом garbage collection удаление Certificate удалит Secret. Для восстановления:

1. Пересоздайте ресурс Certificate с тем же `secretName` — cert-manager автоматически запросит новый сертификат.

2. Если требуется тот же сертификат — восстановите Secret из backup (см. [операции backup/restore](./operations.md)).

### Диагностика проблем

Для проверки состояния Certificate, Order, Challenge и анализа логов используйте [руководство по troubleshooting](./troubleshooting.md). Для мониторинга, алертинга, backup и обновления — [операции cert-manager](./operations.md).

## Additional Information

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Garbage collection | **10** | Официальная документация cert-manager.io |
| Prometheus-метрики | **10** | Встроены в cert-manager с версии 0.11 |
| Troubleshooting | **9** | Основано на официальной документации и опыте |
| Backup/Restore | **9** | Стандартная практика Kubernetes |

