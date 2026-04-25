import mail_run_pipeline
import mail_show_pipeline_status


def main():
    mail_run_pipeline.main()
    return mail_show_pipeline_status.main()


if __name__ == "__main__":
    main()
