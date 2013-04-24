try:
  import json
except ImportError:
  from django.utils import simplejson as json
from google.appengine.ext import db
import pickle
import traceback
import logging
from google.appengine.api import users

from stochssapp import BaseHandler
from stochss.model import *
from stochss.stochkit import *
from stochss.examplemodels import *

# A db property to store objects.
class ObjectProperty(db.Property):
    def get_value_for_datastore(self, model_instance):
        result = super(ObjectProperty, self).get_value_for_datastore(model_instance)
        result = pickle.dumps(result)
        return db.Blob(result)

    def make_value_from_datastore(self, value):
        if value is None:
            return None
        return pickle.loads(value)

    def empty(self, value):
        return value is None


class StochKitModelWrapper(db.Model):
    """
    A wrapper for the StochKit Model object
    """
    user_id = db.StringProperty()
    model_name = db.StringProperty()    
    model = ObjectProperty()
        

class ModelEditorPage(BaseHandler):
    """
    Provides a web UI around POST /model, to allow users to create
    StochKitModelWrappers via the web interface instead of the RESTful one.
    """
    
    def get(self):
        model_edited = self.request.get('model_edited')
        
        if model_edited is not None and model_edited is not "":
            result = self.edit_model(model_edited)
            result = dict(get_all_models(self), **result)
        
        elif self.request.get('get_model_edited') == "1":
            result = self.get_model_edited()    
            self.response.headers['Content-Type'] = 'application/json'
            self.response.write(json.dumps(result))
            return
            
        else:
            result = get_all_models(self)
        
        self.render_response('modeleditor.html', **result)


    def post(self):
        # First, check to see if it's a save_changes request and then route it to the appropriate function.
        save_changes = self.request.get('save_changes')
        if save_changes is not "":
            result = self.save_model(save_changes)
            self.response.headers['Content-Type'] = 'application/json'
            self.response.write(json.dumps(result))
            
        elif self.request.get("delete") == "1":
            result = self.delete_model()
            result = dict(get_all_models(self), **result)
            self.render_response('modeleditor.html', **result)            
            
        else:
            result = self.create_model()
            result = dict(get_all_models(self), **result)
            self.render_response('modeleditor.html', **result)


    def get_model_edited(self):
        """
        Returns the current model that is being edited. This would be called asynchronously each time the modeleditor.html loads.
        """
        model_edited = self.get_session_property('model_edited')        
        return {'status': True, 'model_edited': '' if model_edited is None else model_edited.name}
              
              
    def delete_model(self):
        name = self.request.get('toDelete')
        if name == "":
            return {'status': False, 'msg': 'Name is missing'}
        
        try:
            model_edited = self.get_session_property('model_edited')
            
            # If the model selected for deletion is same as the one that is currently being edited,
            if model_edited is not None and model_edited.name == name:
                self.session['model_edited'] = None                
            
            db_model = db.GqlQuery("SELECT * FROM StochKitModelWrapper WHERE user_id = :1 AND model_name = :2", self.user.user_id(), name).get()
            if db_model is None:
                return {'status': False, 'msg': 'The datastore does not have any such entry.'}
            
            db_model.delete()
            all_models = self.get_session_property('all_models')
            all_models.pop(all_models.index(name))
            
            self.set_session_property('all_models', all_models)
            
            return {'status': True, 'msg': name + ' deleted successfully.'}
            
        except Exception, e:
            logging.error("model::delete_model - Deleting the model failed with error: %s", e)
            traceback.print_exc()
            return {'status': False, 'msg': 'There was an error while deleting the model!'}
            
        
    def save_model(self, save_changes):
        """
          Save the changes that were made to the current model.
        """
        try:
            user_id = self.user.user_id()
            model = self.get_session_property('model_edited')
            if model is None:
                return {'status': False, 'msg': 'Model not found in cache!'}
            if save_changes == "0":
                result = {'status': False, 'msg': 'Your recent changes to ' + model.name + ' have been discarded!'}
            else:
                # Flush the data in cache to the datastore.
                db_model = db.GqlQuery("SELECT * FROM StochKitModelWrapper WHERE user_id = :1 AND model_name = :2", user_id, model.name).get()
                db_model.model = model
                db_model.put()
                result = {'status': True, 'msg': model.name + ' saved successfully!'}

            self.set_session_property('is_model_saved', True)

            new_model_name = self.request.get('model_edited')
            # Save called through the modal dialog box
            if new_model_name is not None and new_model_name is not "":
                db_model = db.GqlQuery("SELECT * FROM StochKitModelWrapper WHERE user_id = :1 AND model_name = :2", user_id, new_model_name).get()
                self.set_session_property('model_edited', db_model.model)
            
            # redirect_page refers to the page to be redirected to, after the user chooses to save or discard the recent changes.
            redirect_page = self.request.get('redirect_page')
            if redirect_page != '':
                result['redirect_page'] = redirect_page                            
                    
            return result

        except Exception, e:
            logging.error("model::save_model - Saving the model failed with error: %s", e)
            traceback.print_exc()
            return {'status': False, 'msg': 'There was an error while saving the model.'}


    def edit_model(self, name):
        """
        Update the cache with the model that is being edited.
        """
        try:
            # If the user tries to edit another model before saving all the changes, show a message.
            is_model_saved = self.get_session_property('is_model_saved')
            if is_model_saved is not None and not is_model_saved:
                model_edited = self.get_session_property('model_edited')
                # It is okay if the currently edited model is the same as the newly chosen one.
                if(model_edited.name == name):
                    return {'status': True, 'model_edited': name}
              
                logging.debug('old_model: ' + self.get_session_property('model_edited').name)
                return {'status': False, 'save_msg': 'Please save your changes first!', 'is_saved': False, 'model_edited': name}
            
            db_model = db.GqlQuery("SELECT * FROM StochKitModelWrapper WHERE user_id = :1 AND model_name = :2", self.user.user_id(), name).get()
            self.set_session_property('model_edited', db_model.model)

            return {'status': True, 'model_edited': name}
        except Exception, e:
            logging.error("model::edit_model - Editing the model failed with error: %s", e)
            traceback.print_exc()
            return {'status': False, 'msg': 'There was an error while editing the model.'}

      
    def create_model(self):
        """
          Creates a new ModelWrapper and stores it in the Datastore.
          Parameters:
            name:  To identify the given model.
            model: The Model string

          Returns:
            A dict that indicates the status of this call.
        """
        name = self.request.get('name').strip()
        if not name:
          return {'status': False, 'msg': 'Model name is missing.'}

        model = Model(name)
        try:
          user_id = self.user.user_id()
          logging.debug("user_id " + user_id)  
          
          #db_model = StochKitModelWrapper.get_by_key_name(key_name)
          db_model = db.GqlQuery("SELECT * FROM StochKitModelWrapper WHERE user_id = :1 AND model_name = :2", user_id, name).get()
          
          if db_model is not None:
              return {'status': False, 'msg': 'A Model already exists by that name.', 'name': name}
          
          save_model(model, name, user_id)
          
          # Also add the model name to cache.
          add_model_to_cache(self, name)
          
          # After creating the model and before setting this as the currently edited model, check if the previously edited model was saved.
          is_model_saved = self.get_session_property('is_model_saved')
          if is_model_saved is not None and not is_model_saved:
              logging.debug('old_model: ' + self.get_session_property('model_edited').name)
              return {'status': False, 'save_msg': 'Please save your changes first!', 'is_saved': False, 'model_edited': name}

          # Set the new model as the one that is being edited.
          self.set_session_property('model_edited', model)

          return {'status': True, 'msg': 'Model created successfully!'}
        except Exception, e:
          logging.error("model::create_model: Model creation failed with error %s", e)
          traceback.print_exc()
          return {'status': False, 'msg': 'There was an error while creating the model.'}
      

class ModelEditorImportFromFilePage(BaseHandler):
    
    def get(self):
        self.render_response('modeleditor/importmodelfile.html')        
        
    def post(self):
        result = self.import_model()
        template_file = 'modeleditor/importmodelfile.html'
        # The template file may refer to modeleditor.html for some cases.
        if 'template_file' in result:
            template_file = result['template_file']
        self.render_response(template_file, **result)
        
    def import_model(self):
        name = self.request.get('name').strip()
        if not name:
            return {'status': False, 'msg': 'Model name is missing.'}
        
        file_data = self.request.POST['model_file']
        
        if file_data == "":
            return {'status': False, 'msg': 'No file was chosen to import.'}
        
        logging.debug("file_name: " + file_data.filename)
        
        return do_import(self, name)        

class ModelEditorImportFromLibrary(BaseHandler):
    
    def get(self):
        example_library = self.get_library()
        self.render_response('modeleditor/importfromlibrary.html', **{'example_library': example_library})
        
    def post(self):
        result = self.import_model()
        template_file = 'modeleditor/importfromlibrary.html'
        # The template file may refer to modeleditor.html for some cases.
        if 'template_file' in result:
            template_file = result['template_file']
        result = dict({'example_library': self.get_library()}, **result)    
        self.render_response(template_file, **result)
    
    def get_library(self):
        # For now, it is hard-coded here.
        return ['dimerdecay', 'MichaelisMenten']
                
    def import_model(self):
        name = self.request.get('name').strip()
        if name == "":
            return {'status': False, 'msg': 'Model name is missing.'}
        
        model_class = self.request.get('model_class')   
        return do_import(self, name, False, model_class)   

def do_import(handler, name, from_file = True, model_class=""):
    """
        Helper function to import models from file / library.
        """
    try:
        user_id = handler.user.user_id()
        db_model = db.GqlQuery("SELECT * FROM StochKitModelWrapper WHERE user_id = :1 AND model_name = :2", user_id, name).get()
        
        if db_model is not None:
            return {'status': False, 'msg': 'A Model already exists by that name.'}
        
        if from_file:
            doc = StochMLDocument.fromFile(handler.request.POST['model_file'].file)
            model = doc.toModel(name)
        
        else:
            if model_class == 'dimerdecay':
                model = dimerdecay(name)
            elif model_class == 'MichaelisMenten':
                model = MichaelisMenten(name)
            else:
                return {'status': False, 'msg': 'Invalid model class'}

        # For the model to display and function properly in the UI, we need to make sure that all
        # the parameters have been resolved to scalar values.
        try:
            model.resolveParameters()
        # Save the model so the resolved parameter values are persisted
        #save_model(model, name, user_id)
        except:
            raise ModelError("Could not resolve model parameters.")
    
        # Save the model to the datastore.
        save_model(model, name, user_id)
        
        # Add this model to cache
        add_model_to_cache(handler, name)
        
        # After importing the model and before setting this as the currently edited model, check if the previously edited model was saved.
        is_model_saved = handler.get_session_property('is_model_saved')
        if is_model_saved is not None and not is_model_saved:
            logging.debug("Model not saved!")
            return {'status': False, 'save_msg': 'Please save your changes first!', 'is_saved': False, 'template_file': 'modeleditor.html', 'model_edited': name, 'redirect_page': '/modeleditor'}

        # Set the new model as the one that is being edited.
        handler.set_session_property('model_edited', model)
            
    except Exception, e:
        logging.error("model::import_model failed with error %s", e)
        traceback.print_exc()
        return {'status': False, 'msg': 'Model could not be imported.'}

    return {'status': True, 'msg': 'Model imported successfully.'}


class ModelEditorExportToStochkit2(BaseHandler):
    def get(self):
        model = self.get_session_property('model_edited')
        if model is None:
            result = {'status': False, 'msg': 'You have not selected any model to export.'}
            result = dict(get_all_models(self), **result)
            self.render_response('modeleditor.html', **result)
            return
        try:
            doc = model.serialize()
            self.response.headers['Content-Type'] = 'text/xml'
            self.response.headers['Content-Disposition'] = 'attachment;filename=' + model.name.encode('utf-8') + '.xml'
            self.response.write(doc)
        except Exception, e:
            logging.error('Error in exporting to StochML. %s', e)
            traceback.print_exc()
            result = {'status': False, 'msg': 'There was an error while exporting to StochML.'}
            result = dict(get_all_models(self), **result)
            self.render_response('modeleditor.html', **result)


def save_model(model, model_name, user_id):
    """ Save model as a new entity. """
    db_model = StochKitModelWrapper()
    db_model.user_id = user_id
    db_model.model = model
    db_model.model_name = model_name
    db_model.put()

def add_model_to_cache(obj, new_model_name):
    """
    Adds the given model name to the cache (only if it is not already there).
    """
    all_models_cache = obj.get_session_property('all_models')
    if all_models_cache is None:
        all_models_cache = []
        
    if not new_model_name in all_models_cache:
        all_models_cache.append(new_model_name)
        obj.set_session_property('all_models', all_models_cache)
        logging.debug("Model added to cache.")



def get_all_models(handler):
    """
      Retrieves all models from the cache. If the cache is not already populated, db_models the datastore, populate the cache and then return it.
    """
    try:
        all_models = handler.get_session_property('all_models')
        logging.debug("handler.user.user_id() " + handler.user.user_id())
        logging.debug("all_models " + str(all_models))
        if all_models is None:
            db_models = db.GqlQuery("SELECT * FROM StochKitModelWrapper WHERE user_id = :1", handler.user.user_id())
            logging.debug("here")
            if db_models is not None:
                all_models = [row.model_name for row in db_models]
                handler.set_session_property('all_models', all_models)

        return {'status': True, 'all_models': all_models}

    except Exception, e:
        logging.error("model::get_all_models - Error retrieving all the models: %s", e)
        traceback.print_exc()
        return {'status': False, 'msg': 'There was an error while getting all the models.'}
        