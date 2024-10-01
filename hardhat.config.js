require("@nomicfoundation/hardhat-toolbox");
dotenv = require("dotenv")
dotenv.config()

const accounts = {
  mnemonic: process.env.MNEMONIC || "test test test test test test test test test test test junk",
  accountsBalance: "100000000000000000000000000000",
}

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  networks: {
    hardhat: {
      forking: {
        url: process.env.WEB3_PROVIDER_URL,
        blockNumber: 20233401,
        // blockNumber: 20825292,
      },
      accounts,
    }
  },
}
