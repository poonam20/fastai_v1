
        #################################################
        ### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
        #################################################

class HPOptimizer():
    
    def __init__(self, params, opt_fn, init_lr):
        self.opt = opt_fn(params, init_lr)
        self._lr = init_lr
        self.opt_keys = list(self.opt.param_groups[0].keys())
        self.opt_keys.remove('params')
        self.read_defaults()
    
    #Pytorch optimizer methods
    def step(self):
        self.opt.step()
    
    def zero_grad(self):
        self.opt.zero_grad()
    
    #Hyperparameters as properties
    @property
    def lr(self): return self._lr

    @lr.setter
    def lr(self, val):
        self.set_val('lr', val)
        self._lr = val
    
    @property
    def mom(self): return self._mom

    @mom.setter
    def mom(self, val):
        if 'momentum' in self.opt_keys: self.set_val('momentum', val)
        elif 'betas' in self.opt_keys:  self.set_val('betas', (val, self._beta))
        self._mom = val
    
    @property
    def beta(self): return self._beta

    @beta.setter
    def beta(self, val):
        if 'betas' in self.opt_keys:    self.set_val('betas', (self._mom,val))
        elif 'alpha' in self.opt_keys:  self.set_val('alpha', val)
        self._beta = val
    
    @property
    def wd(self): return self._wd

    @wd.setter
    def wd(self, val):
        self.set_val('weight_decay', val)
        self._wd = val
    
    #Helper functions
    def read_defaults(self):
        if 'momentum' in self.opt_keys: self._mom = self.opt.param_groups[0]['momentum']
        if 'alpha' in self.opt_keys: self._beta = self.opt.param_groups[0]['alpha']
        if 'betas' in self.opt_keys: self._mom,self._beta = self.opt.param_groups[0]['betas']
        if 'weight_decay' in self.opt_keys: self._wd = self.opt.param_groups[0]['weight_decay']
    
    def set_val(self, key, val):
        for pg in self.opt.param_groups: pg[key] = val

def annealing_no(start, end, pct): return start
def annealing_linear(start, end, pct): return start + pct * (end-start)
def annealing_exponential(start, end, pct): return start * (end/start) ** pct

class Stepper():
    
    def __init__(self, start, end, num_it, ft):
        self.start,self.end,self.num_it,self.ft = start,end,num_it,ft
        self.n = 0
    
    def step(self):
        self.n += 1
        return self.ft(self.start, self.end, self.n/self.num_it)
    
    def is_done(self):  return self.n >= self.num_it
    def init_val(self): return self.start

class OneCycleScheduler(Callback):
    
    def __init__(self, learn, lr_max, epochs, moms=(0.95,0.85), div_factor=10, pct_end=0.1):
        self.learn = learn
        a = int(len(learn.data.train_dl) * epochs * (1 - pct_end) / 2)
        b = int(len(learn.data.train_dl) * epochs * pct_end)
        self.lr_scheds = [Stepper(lr_max/div_factor, lr_max, a, annealing_linear),
                          Stepper(lr_max, lr_max/div_factor, a, annealing_linear),
                          Stepper(lr_max/div_factor, lr_max/(div_factor*100), b, annealing_linear)]
        self.mom_scheds = [Stepper(moms[0], moms[1], a, annealing_linear),
                          Stepper(moms[1], moms[0], a, annealing_linear),
                          Stepper(moms[0], None, b, annealing_no)]
    
    def on_train_begin(self):
        self.opt = self.learn.opt
        self.opt.lr, self.opt.mom = self.lr_scheds[0].init_val(), self.mom_scheds[0].init_val()
        self.idx_s = 0
    
    def on_batch_end(self, loss):
        self.opt.lr = self.lr_scheds[self.idx_s].step()
        self.opt.mom = self.mom_scheds[self.idx_s].step()
        if self.lr_scheds[self.idx_s].is_done():
            self.idx_s += 1
            if self.idx_s >= len(self.lr_scheds): return True

class LRFinder(Callback):
    #TODO: add model.save in init or on_train_begin and model.load in on_train_end.
    
    def __init__(self, learn, start_lr=1e-5, end_lr=10, num_it=200):
        self.learn = learn
        self.sched = Stepper(start_lr, end_lr, num_it, annealing_exponential)
        #To avoid validating if the train_dl has less than num_it batches, we put aside the valid_dl and remove it
        #during the call to fit.
        self.valid_dl = learn.data.valid_dl
        learn.data.valid_dl = None
    
    def on_train_begin(self):
        self.opt = self.learn.opt
        self.opt.lr = self.sched.init_val()
        self.stop,self.first,self.best_loss = False,True,0.
    
    def on_batch_end(self, loss):
        if self.first or loss < self.best_loss:
            self.first = False
            self.best_loss = loss
        self.opt.lr = self.sched.step()
        if self.sched.is_done() or self.learn.recorder.smooth_loss > 4*self.best_loss:
            #We use the smoothed loss to decide on the stopping since it's less shaky.
            self.stop=True
            return True
    
    def on_epoch_end(self, val_loss): return self.stop
    
    def on_train_end(self):
        #Clean up and put back the valid_dl in its place.
        self.learn.data.valid_dl = self.valid_dl

class Learner():
    def __init__(self, data, model):
        self.data,self.model = data,model.to(data.device)
        self.loss_fn, self.opt_fn, self.metrics = F.cross_entropy, optim.SGD, []

    def fit(self, epochs, lr, callbacks=[]):
        self.opt = HPOptimizer(self.model.parameters(), self.opt_fn, init_lr=lr)
        self.recorder = Recorder(self.opt, self.data.train_dl)
        callbacks.insert(0, self.recorder)
        fit(epochs, self.model, self.loss_fn, self.opt, self.data, callbacks=callbacks, metrics=self.metrics)
        
    def lr_find(self, start_lr=1e-5, end_lr=10, num_it=200):
        cb = LRFinder(self, start_lr, end_lr, num_it)
        a = int(np.ceil(num_it/len(self.data.train_dl)))
        self.fit(a, start_lr, callbacks=[cb])

def loss_batch(model, xb, yb, loss_fn, opt=None, cb_handler=CallbackHandler([]), metrics=[]):
    out = model(xb)
    loss = loss_fn(out, yb)
    mets = [f(out,yb).item() for f in metrics]
    
    if opt is not None:
        loss = cb_handler.on_backward_begin(loss, out)
        loss.backward()
        cb_handler.on_backward_end()
        opt.step()
        cb_handler.on_step_end()
        opt.zero_grad()
        
    return (loss.item(),) + tuple(mets) + (len(xb),)

def fit(epochs, model, loss_fn, opt, data, callbacks=[], metrics = []):
    
    cb_handler = CallbackHandler(callbacks)
    cb_handler.on_train_begin()
    
    for epoch in tnrange(epochs):
        model.train()
        cb_handler.on_epoch_begin()
        
        for xb,yb in data.train_dl:
            xb, yb = cb_handler.on_batch_begin(xb, yb)
            loss,_ = loss_batch(model, xb, yb, loss_fn, opt, cb_handler)
            if cb_handler.on_batch_end(loss): break
        
        if hasattr(data,'valid_dl') and data.valid_dl is not None:
            model.eval()
            with torch.no_grad():
                *val_metrics,nums = zip(*[loss_batch(model, xb, yb, loss_fn, metrics=metrics)
                                for xb,yb in data.valid_dl])
            val_metrics = [np.sum(np.multiply(val,nums)) / np.sum(nums) for val in val_metrics]
            
        else: val_metrics=None
        if cb_handler.on_epoch_end(val_metrics): break
        
    cb_handler.on_train_end()

class Callback():
    def on_train_begin(self): pass         
        #To initiliaze constants in the callback.
    def on_epoch_begin(self): pass
        #At the beginning of each epoch
    def on_batch_begin(self, xb, yb): pass 
        #To set HP before the step is done. A look at the input can be useful (set the lr depending on the seq_len in RNNs, 
        #or for reg_functions called in on_backward_begin)
        #Returns xb, yb (which can allow us to modify the input at that step if needed)
    def on_backward_begin(self, loss, out): pass
        #Called after the forward pass and the loss has been computed, but before the back propagation.
        #Passes the loss and the output of the model.
        #Returns the loss (which can allow us to modify it, for instance for reg functions)
    def on_backward_end(self): pass
        #Called after the back propagation had been done (and the gradients computed) but before the step of the optimizer.
        #Useful for true weight decay in AdamW
    def on_step_end(self): pass
        #Called after the step of the optimizer but before the gradients are zeroed (not sure this one is useful)
    def on_batch_end(self, loss): pass
        #Called at the end of the batch
    def on_epoch_end(self, val_metrics): pass
        #Called at the end of an epoch
    def on_train_end(self): pass
        #Useful for cleaning up things and saving files/models

class CallbackHandler():
    
    def __init__(self, callbacks):
        self.callbacks = callbacks
    
    def __call__(self, cb_name, *args, **kwargs):
        return [getattr(cb, f'on_{cb_name}')(*args, **kwargs) for cb in self.callbacks]
    
    def on_train_begin(self): self('train_begin')
    def on_epoch_begin(self): self('epoch_begin')
        
    def on_batch_begin(self, xb, yb):
        for cb in self.callbacks:
            a = cb.on_batch_begin(xb,yb)
            if a is not None: xb,yb = a
        return xb,yb
    
    def on_backward_begin(self, loss, out):
        for cb in self.callbacks:
            a = cb.on_backward_begin(loss, out)
            if a is not None: loss = a
        return loss
    
    
    def on_backward_end(self):        self('backward_end')
    def on_step_end(self):            self('step_end')
    def on_batch_end(self, loss):     return np.any(self('batch_end', loss))
    def on_epoch_end(self, val_metrics): return np.any(self('epoch_end', val_metrics))
    def on_train_end(self):           self('train_end')