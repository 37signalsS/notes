# Практическое руководство: Авторизация GitLab Runner в Kubernetes

В этом руководстве рассматриваются два способа авторизации для runner'ов, взаимодействующих с кластером k8s.

## Способ 1: Авторизация через `KUBE_CONFIG` в CI/CD переменных

Этот способ, наиболее простой, состоит в том, чтобы добавить переменную `KUBE_CONFIG` для подключения к удаленному кластеру в переменные GitLab CI.

1.  Запустите стенд и подключитесь к мастер-ноде Kubernetes:

    ```bash
    ssh sbox.slurm.io
    ssh master-1.sXXXXXX # Где sXXXXXX - ваш номер
    sudo -i
    ```

2.  Получите конфигурацию kubeconfig в формате base64:

    ```bash
    cat /root/.kube/config | base64 -w 0 ; echo
    ```

3.  Сохраните вывод последней команды.

4.  В вашем проекте GitLab перейдите в **Settings -> CI/CD** и раскройте раздел **Variables**.

5.  Нажмите **Add variable** и добавьте переменную:
    *   **Key:** `K8S_CONFIG`
    *   **Value:** Вставьте содержимое, скопированное с мастер-ноды.
    *   **Flags:** Оставьте значения по умолчанию.

    Данные переменные хранятся в зашифрованном виде в базе данных GitLab, поэтому их можно использовать для хранения чувствительных данных.

6.  Убедитесь, что для проекта включены "Shared runners".

7.  Создайте `.gitlab-ci.yml` со следующим содержимым:

    ```yaml
    stages:
      - kubectl

    kubectl-check:
      stage: kubectl
      image:
        name: bitnami/kubectl:1.21.13
        entrypoint: [""]
      variables:
        KUBECONFIG: /tmp/.kubeconfig
      script:
        - echo "$K8S_CONFIG" | base64 -d > $KUBECONFIG
        - kubectl get nodes
    ```

При условии, что есть сетевая доступность между средой runner'a и API-сервером k8s, вы увидите, как pipeline успешно взаимодействует с кластером и получает список его узлов.

*Дополнительная информация о переменных GitLab CI:* [Типы переменных CI/CD](https://docs.gitlab.com/ee/ci/variables/#cicd-variable-types)

---

## Способ 2: In-cluster авторизация с Kubernetes Executor

Альтернативно можно запускать пайплайны внутри кластера, используя Kubernetes executor. Это рекомендуемый и более безопасный подход.

1.  Перейдите на мастер-ноду кластера и подготовьте кластер для работы с Kubernetes executor:

    ```bash
    # Создаем неймспейс для раннера
    kubectl create ns runner

    # Создаем ServiceAccount для раннера
    kubectl create sa runner -n runner

    # Даем ServiceAccount права cluster-admin (для примера, в проде используйте более гранулярные права)
    kubectl create clusterrolebinding runner-cluster-admin --clusterrole=cluster-admin --serviceaccount=runner:runner
    ```

2.  Зарегистрируйте новый runner. Это можно сделать с помощью скрипта `register.sh` или через API GitLab. При регистрации укажите `kubernetes` в качестве executor'а.

    *Пример регистрации с помощью скрипта:*
    ```bash
    $ ./register.sh

    Please enter the gitlab-ci coordinator URL: https://gitlab.slurm.io/
    Please enter the gitlab-ci token for this runner: XXXXXXXXXXXXXXXXXXXX
    Please enter the gitlab-ci description for this runner: kubernetes
    Please enter the gitlab-ci tags for this runner (comma separated): sXXXXXX,kubernetes
    Registering runner... succeeded
    Please enter the executor: kubernetes
    ```

3.  Сформированный конфиг (`/etc/gitlab-runner/config.toml`) должен иметь подобный вид. **Ключевая строка `service_account_overwrite_allowed` - её необходимо добавить самостоятельно.**

    ```toml
    concurrent = 1
    check_interval = 0

    [session_server]
      session_timeout = 1800

    [[runners]]
      name = "kubernetes"
      url = "https://gitlab.slurm.io/"
      token = "XXXXXXXXXXXXXXXXXXXX"
      executor = "kubernetes"
      [runners.kubernetes]
        namespace = "runner"
        # Эта строка разрешает пайплайну использовать указанный ServiceAccount
        service_account_overwrite_allowed = ".*" 
    ```
    *Примечание: В `service_account_overwrite_allowed` можно использовать регулярное выражение для ограничения разрешенных ServiceAccounts.*

4.  Скопируйте измененный `config.toml` на мастер-ноду k8s и создайте `ConfigMap` из него:
    ```bash
    kubectl create configmap runner --from-file=config.toml -n runner
    ```

5.  Примените к кластеру манифест для развертывания самого runner'а (например, `runner.yml`).
    ```bash
    kubectl apply -f runner.yml
    ```
    Спустя несколько секунд изменения отобразятся в веб-интерфейсе GitLab в разделе **Settings -> CI/CD -> Runners**.

6.  Теперь, используя этот раннер, можно получить доступ в кластер следующим образом в `.gitlab-ci.yml`:

    ```yaml
    stages:
      - kubectl

    kubectl-check-in-cluster:
      stage: kubectl
      tags:
        - <ваш_тег_раннера> # например, kubernetes
      image:
        name: bitnami/kubectl:1.21.13
      variables:
        # Переопределяем ServiceAccount для пода, в котором будет выполняться задача
        KUBERNETES_SERVICE_ACCOUNT_OVERWRITE: runner
      script:
        # Конфигурация kubectl для использования встроенного ServiceAccount токена
        - kubectl config set-cluster local --server=https://kubernetes.default.svc --certificate-authority=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        - kubectl config set-context local --cluster=local
        - kubectl config set-credentials user --token=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
        - kubectl config use-context local --user=user
        - kubectl get nodes
    ```

Как и в предыдущем случае, в логе пайплайна будут отображены серверы кластера, что подтверждает успешную авторизацию.
