import os
import subprocess
import time
import argparse


def should_update_local(local_commit, remote_commit):
    return local_commit != remote_commit


def autoupdate_validator_steps(proc):
    os.system(f"./autoupdate_validator_steps.sh {proc}")

    time.sleep(20)


def run_auto_updater(args):
    while True:
        current_branch = subprocess.getoutput("git rev-parse --abbrev-ref HEAD")
        local_commit = subprocess.getoutput("git rev-parse HEAD")
        os.system("git fetch")
        remote_commit = subprocess.getoutput(f"git rev-parse origin/{current_branch}")

        if should_update_local(local_commit, remote_commit):
            print("Local repo is not up-to-date. Updating...")
            reset_cmd = "git reset --hard " + remote_commit
            process = subprocess.Popen(reset_cmd.split(), stdout=subprocess.PIPE)
            output, error = process.communicate()

            if error:
                print("Error in updating:", error)
            else:
                print("Updated local repo to latest version: {}", format(remote_commit))

                print("Running the autoupdate steps...")
                # Trigger shell script. Make sure this file path starts from root
                autoupdate_validator_steps(args.proc)

                print("Finished running the autoupdate steps! Ready to go 😎")

        else:
            print("Repo is up-to-date.")

        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--proc",
        type=str,
        required=True,
        help="Name or id of validator's pm2 process \
                        (run pm2 ls to check it)",
    )
    args = parser.parse_args()
    run_auto_updater(args)
