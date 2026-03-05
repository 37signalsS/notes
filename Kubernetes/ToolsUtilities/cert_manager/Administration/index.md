# Администрирование Cert-manager

## Определения

**Администрирование cert-manager** — управление жизненным циклом сертификатов, диагностика, мониторинг и обеспечение безопасности.

> **Навигация:** [Troubleshooting](./troubleshooting.md) | [Операции](./operations.md)

---

## Basic Concepts

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

---

## Файлы

| Файл | Описание |
|------|----------|
| [troubleshooting.md](./troubleshooting.md) | Диагностика, проверка состояния, логи, частые проблемы |
| [operations.md](./operations.md) | Мониторинг, алертинг, backup, обновление, безопасность |

---

## Additional Information

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Garbage collection | **10** | Официальная документация cert-manager.io |
| Prometheus-метрики | **10** | Встроены в cert-manager с версии 0.11 |
| Troubleshooting | **9** | Основано на официальной документации и опыте |
| Backup/Restore | **9** | Стандартная практика Kubernetes |

### Связанные темы

- [Private CA](../private_ca.md) — создание собственного CA
- [LetsEncrypt](../LetsEncrypt/) — практические сценарии с Let's Encrypt
- [Installation](../install.md) — установка cert-manager
