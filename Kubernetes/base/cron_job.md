# CronJob

Если вам нужно выполнять [Job](./job.md) не один раз, а по расписанию (например, каждую ночь для создания бэкапа), используйте **CronJob**. Он работает как системный `cron` в Linux, но для Kubernetes.

`CronJob` создаёт объекты `Job` в соответствии с заданным расписанием в формате `cron`.

### Пример `CronJob`

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: backup-cronjob
spec:
  # Запускать каждый день в 2 часа ночи
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup-container
            image: backup-tool
            command: ["/bin/sh", "-c", "run-backup.sh"]
          restartPolicy: OnFailure
```
