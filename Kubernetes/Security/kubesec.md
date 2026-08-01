# Kubesec: Анализ рисков и сканер безопасности в Kubernetes

## Определения

**Kubesec** — это инструмент с открытым исходным кодом для статического анализа безопасности манифестов Kubernetes (YAML). Он оценивает риски конфигурации и выставляет оценку (score) на основе соответствия лучшим практикам безопасности ControlPlane и CIS Benchmark.

* **Статический анализ (SAST):** Проверка манифестов на этапе разработки или в CI/CD до момента их деплоя в кластер.
* **Shift-Left Security:** Стратегия переноса проверок безопасности на максимально ранние этапы жизненного цикла разработки (SDLC).
* **Score (Оценка):** Агрегированное числовое значение, где отрицательный результат сигнализирует о наличии критических уязвимостей.

**Важно:** Kubesec фокусируется на логике безопасности внутри манифестов. Для валидации синтаксиса и соответствия схемам API он интегрируется с [Kubeconform](https://github.com/yannh/kubeconform). Для проверки конфигурации работающего кластера используйте [kube-bench](./kube-bench.md).

## Основные концепции

* **Анализ ресурсов:** Поддержка проверки Pod, Deployment, Service, DaemonSet, StatefulSet, CronJob, а также `initContainers` и `volumeClaimTemplates`.
* **Vigilant Mode (Бдительный режим):** Набор ужесточенных правил, требующий явного определения ограничений (например, обязательный `readOnlyRootFilesystem`).
* **Интеграция со схемами:** В современных версиях (v2+) Kubesec использует библиотеки валидации схем для проверки корректности структуры манифеста перед анализом безопасности.
* **Kubesec-as-a-Service:** Публичный API (`v2.kubesec.io/scan`) для быстрых проверок без установки локального окружения.
* **Встроенный HTTP-сервер:** Возможность запуска в режиме `serve` для создания внутреннего сервиса безопасности внутри корпоративной сети.

## Система оценки и правила

Kubesec начисляет или вычитает баллы на основе обнаруженных настроек. Подробное техническое описание этих параметров приведено в **[Security Context в Kubernetes](./pod_security_context.md)**.
 Если итоговый балл **ниже 0**, манифест считается небезопасным для использования в production.

| Правило | Описание | Баллы |
| :--- | :--- | :--- |
| **Privileged** | Контейнер запущен с флагом `privileged: true`. | **-30** |
| **HostNetwork/IPC/PID** | Использование пространств имен хоста (риск выхода на хост). | **-10** |
| **ReadOnlyRootFilesystem** | Файловая система контейнера доступна только для чтения. | **+30** |
| **RunAsNonRoot** | Запрет запуска процесса от пользователя root. | **+10** |
| **Capabilities** | Проверка на наличие опасных Linux capabilities (например, `CAP_SYS_ADMIN`). | **-10** |
| **AllowPrivilegeEscalation** | Разрешение процессу повышать свои привилегии. | **-10** |

## Практические сценарии

### Установка Kubesec

* **Использование через Docker:**

    ```bash
    docker run -i kubesec/kubesec:v2 scan /dev/stdin < pod.yaml
    ```

* **Установка бинарного файла (Linux/macOS):**

    ```bash
    curl -sSL https://github.com/controlplaneio/kubesec/releases/download/v2.11.0/kubesec_linux_amd64.tar.gz | tar -xz
    chmod +x ./kubesec
    mv ./kubesec /usr/local/bin/
    ```

* **Установка как плагин kubectl:**

    ```bash
    kubectl krew install kubesec
    ```

### Примеры использования

* **Сканирование локального манифеста с выводом в JSON:**

    ```bash
    kubesec scan deployment.yaml
    # → [
    #    {
    #      "object": "Deployment/secure-app.default",
    #      "valid": true,
    #      "score": 5,
    #      "message": "Passed with a score of 5",
    #      "scoring": { ... }
    #    }
    #  ]
    ```

* **Сканирование Helm-чарта (рендеринг "на лету"):**

    ```bash
    helm template my-release ./charts/my-app | kubesec scan /dev/stdin
    ```

* **Использование публичного API (без установки):**

    ```bash
    curl -sS --request POST --data-binary @pod.yaml https://v2.kubesec.io/scan
    ```

### Интеграция в CI/CD

#### GitHub Actions (рекомендуемый подход)

Блокировка пайплайна при обнаружении критических проблем:

```yaml
jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Kubesec
        run: |
          # Сканируем и проверяем, что score >= 0
          docker run -i kubesec/kubesec:v2 scan /dev/stdin < k8s/manifest.yaml > result.json
          SCORE=$(cat result.json | jq '.[0].score')
          if [ "$SCORE" -lt 0 ]; then
            echo "Critical security risks found!"
            exit 1
          fi
```

## Дополнительная информация

### Сравнение с другими инструментами

* [Kyverno](./kyverno/policies/practical_scenarios.md) — динамическое применение политик (Admission Control) внутри кластера.
* [kube-bench](./kube-bench.md) — проверка конфигурации узлов и контрол-плейна на соответствие CIS.
* [Falco](../../Security/Tools/falco.md) — обнаружение аномалий и угроз в режиме реального времени (Runtime Security).

**Ссылки:**

* [Официальный репозиторий проекта](https://github.com/controlplaneio/kubesec)
* [Полный список правил и документация](https://kubesec.io)
