require("@nomicfoundation/hardhat-toolbox");
dotenv = require("dotenv")
dotenv.config()

const accounts = {
  mnemonic: process.env.MNEMONIC || "test test test test test test test test test test test junk",
  accountsBalance: "1000000000000000000000000",
}

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  networks: {
    hardhat: {
      forking: {
        url: process.env.MAINNET_FORKING_URL,
        blockNumber: 20231449,
      },
      accounts,
    }
  },
}
