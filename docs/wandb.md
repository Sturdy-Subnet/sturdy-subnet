# Setup Wandb

Before running your miner and validator, you may also choose to set up Weights & Biases (WANDB). It
is a popular tool for tracking and visualizing machine learning experiments, and we use it for
logging and tracking key metrics across miners and validators, all of which is available publicly
[here](https://wandb.ai/shr1ftyy/sturdy-subnet/table?nw=nwusershr1ftyy). We ***highly recommend***
validators use wandb, as it allows subnet developers and miners to diagnose issues more quickly and
effectively, say, in the event a validator were to be set abnormal weights. Wandb logs are
collected by default, and done so in an anonymous fashion, but we recommend setting up an account
to make it easier to differentiate between validators when searching for runs on our dashboard. If
you would *not* like to run WandB, you can do so by adding the flag `--wandb.off` when running your
miner/validator.

Before getting started, as mentioned previously, you'll first need to
[register](https://wandb.ai/login?signup=true) for a WANDB account, and then set your API key on
your system. Here's a step-by-step guide on how to do this on Ubuntu:

#### Step 1: Installation of WANDB

Before logging in, make sure you have the WANDB Python package installed. If you haven't installed
it yet, you can do so using pip:

```bash
# Should already be installed with the sturdy repo
pip install wandb
```

#### Step 2: Obtain Your API Key

1. Log in to your Weights & Biases account through your web browser.
2. Go to your account settings, usually accessible from the top right corner under your profile.
3. Find the section labeled "API keys".
4. Copy your API key. It's a long string of characters unique to your account.

#### Step 3: Setting Up the API Key in Ubuntu

To configure your WANDB API key on your Ubuntu machine, follow these steps:

1. **Log into WANDB**: Run the following command in the terminal:

   ```bash
   wandb login
   ```

2. **Enter Your API Key**: When prompted, paste the API key you copied from your WANDB account
   settings. 

   - After pasting your API key, press `Enter`.
   - WANDB should display a message confirming that you are logged in.

3. **Verifying the Login**: To verify that the API key was set correctly, you can start a small
   test script in Python that uses WANDB. If everything is set up correctly, the script should run
   without any authentication errors.

4. **Setting API Key Environment Variable (Optional)**: If you prefer not to log in every time, you
   can set your API key as an environment variable in your `~/.bashrc` or `~/.bash_profile` file:

   ```bash
   echo 'export WANDB_API_KEY=your_api_key' >> ~/.bashrc
   source ~/.bashrc
   ```

   Replace `your_api_key` with the actual API key. This method automatically authenticates you with
   wandb every time you open a new terminal session.