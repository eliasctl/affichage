const crypto = require('crypto');

module.exports = {
  SECRET_KEY: process.env.SECRET_KEY || crypto.randomBytes(24).toString('hex'),
  ADMIN_PASSWORD: process.env.ADMIN_PASSWORD || 'change-moi',
};
