# Установка Cert-manager

Существует два основных способа установки `cert-manager`: через Helm (рекомендуемый) и напрямую через манифесты.

## 1. Установка через Helm (рекомендуемый способ)

Helm упрощает управление версиями и конфигурацией `cert-manager`.

### Шаг 1: Добавление репозитория Jetstack

```bash
helm repo add jetstack https://charts.jetstack.io
```

### Шаг 2: Обновление локального кэша Helm

```bash
helm repo update
```

### Шаг 3: Установка cert-manager

> **Важно:** Перед установкой всегда рекомендуется проверять [официальную документацию](https://cert-manager.io/docs/installation/) на предмет последней актуальной версии Helm-чарта.

```bash
helm install \
  cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.13.2 \
  --set installCRDs=true
```

* `--namespace cert-manager`: Устанавливает `cert-manager` в отдельный namespace.
* `--create-namespace`: Создает namespace, если он не существует.
* `--set installCRDs=true`: Эта опция указывает Helm-чарту установить и управнить CRD.

## 2. Установка через манифесты (`kubectl apply`)

Этот способ не требует наличия Helm и заключается в прямом применении YAML-манифеста, который содержит все необходимые ресурсы (CRD, Deployment, RBAC и т.д.).

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.5.0/cert-manager.yaml
```

> **Внимание:** Замените `v1.5.0` на актуальную версию из [официального репозитория](https://github.com/cert-manager/cert-manager/releases).

**Плюсы:**
*   Простота и отсутствие зависимости от Helm.

**Минусы:**
*   Обновление и откат версий выполняются вручную.
*   Управление конфигурацией менее гибкое по сравнению с Helm values.

---

*Основа: [](../cert_manager.md)*
