import tensorflow as tf
from losses import *
from modules import *
from discriminators import *

class STN(tf.keras.Model):
  def __init__(self, config):
    super().__init__()

  def call(self, x):
    pass

class Generator(tf.keras.Model):
  def __init__(self, config):
    super().__init__()
    self.config=config
    self.E = self.build_encoder()
    self.stn = STN(config)
    
  def call(self, x):
    return
  
  def wrap(self, x):
    return
  
  def build_encoder(self):
    nce_layers = self.config['nce_layers']
    outputs = []
    for idx in nce_layers:
      outputs.append(self.layers[idx].output)
    return tf.keras.Model(inputs=self.input, outputs=outputs)


class PatchSampler(tf.keras.Model):
    def __init__(self, config, **kwargs):
        super(PatchSampleMLP, self).__init__(**kwargs)
        self.units = config['units']
        self.num_patches = config['num_patches']
        self.l2_norm = layers.Lambda(lambda x: x * tf.math.rsqrt(tf.reduce_sum(tf.square(x), axis=-1, keepdims=True) + 1e-10))

    def build(self, input_shape):
        initializer = tf.random_normal_initializer(0., 0.02)
        feats_shape = input_shape
        for feat_id in range(len(feats_shape)):
            mlp = tf.keras.models.Sequential([
                    layers.Dense(self.units, activation="relu", kernel_initializer=initializer),
                    layers.Dense(self.units, kernel_initializer=initializer),
                ])
            setattr(self, f'mlp_{feat_id}', mlp)

    def call(self, inputs, patch_ids=None, training=None):
        feats = inputs
        samples = []
        ids = []
        for feat_id, feat in enumerate(feats):
            B, H, W, C = feat.shape
            feat_reshape = tf.reshape(feat, [B, -1, C])
            if patch_ids is not None:
                patch_id = patch_ids[feat_id]
            else:
                patch_id = tf.random.shuffle(tf.range(H * W))[:min(self.num_patches, H * W)]
            x_sample = tf.reshape(tf.gather(feat_reshape, patch_id, axis=1), [-1, C])
            mlp = getattr(self, f'mlp_{feat_id}')
            x_sample = mlp(x_sample)
            x_sample = self.l2_norm(x_sample)
            samples.append(x_sample)
            ids.append(patch_id)
        return samples, ids

class CUTSTN(tf.keras.Model):
  def __init__(self, config):
    super().__init__()
    self.G = Generator(config)
    self.D = Discriminator(config)
    self.F = PatchSampler(config)
    self.config = config
  def compile(self,
              G_optimizer,
              F_optimizer,
              D_optimizer):
      super(CUT, self).compile()
      self.G_optimizer = G_optimizer
      self.F_optimizer = F_optimizer
      self.D_optimizer = D_optimizer
      self.nce_loss_func = PatchNCELoss(self.tau)
  
  @tf.function
  def train_step(self, inputs):
    la, xb = inputs
    
    with tf.GradientTape(persistent=True) as tape:
      #synthesize texture
      xab = self.G(la)
      
      #discrimination
      critic_fake = self.D(xab, training=True)
      critic_real = self.D(xb, training=True)
      
      ###compute losses
      d_loss, g_loss_ = gan_loss(critic_real, critic_fake, self.gan_mode)
      nce_loss = self.nce_loss_func(la, xab, self.G.E, self.F)
      g_loss = g_loss_ + self.config['lambda_nce'] * nce_loss
      
    G_grads = tape.gradient(g_loss, self.G.trainable_weights)
    D_grads = tape.gradient(d_loss, self.D.trainable_weights)
    F_grads = tape.gradient(nce_loss, self.F.trainable_weights)
    
    self.G_optimizer.apply_gradients(zip(G_grads, self.G.trainable_weights))
    self.D_optimizer.apply_gradients(zip(D_grads, self.D.trainable_weights))
    self.F_optimizer.apply_gradients(zip(F_grads, self.F.trainable_weights))
      
    del tape
    
    return {'g_loss': g_loss_, 'd_loss':d_loss, 'nce': nce_loss}
      
  @tf.function
  def test_step(self, inputs):
    la, xb = inputs
    xab = self.G(la) 
    nce_loss = self.nce_loss_func(la, xab, self.G.E, self.F)
    return {'nce': nce_loss}
  
  
  
