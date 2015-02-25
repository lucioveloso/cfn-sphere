__author__ = 'mhoyer'

from boto import cloudformation
from boto.resultset import ResultSet
from boto.exception import AWSConnectionError, BotoServerError
import json
import logging
import time
import os


class CloudFormationTemplate(object):
    def __init__(self, template_url, template_body=None, config_dir=None):
        logging.basicConfig(format='%(asctime)s %(levelname)s %(module)s: %(message)s',
                            datefmt='%d.%m.%Y %H:%M:%S',
                            level=logging.INFO)
        self.logger = logging.getLogger(__name__)

        self.config_dir = config_dir
        self.url = template_url
        self.body = template_body

        if not self.body:
            self.body = self._load_template(self.url)

    def get_template_body(self):
        return self.body

    def _load_template(self, url):
        self.logger.debug("Working in {0}".format(os.getcwd()))
        if url.lower().startswith("s3://"):
            return self._s3_get_template(url)
        else:
            return self._fs_get_template(url)

    def _fs_get_template(self, url):
        if not os.path.isabs(url) and self.config_dir:
            url = os.path.join(self.config_dir, url)

        try:
            with open(url, 'r') as template_file:
                return json.loads(template_file.read())
        except ValueError as e:
            self.logger.error("Could not load template from {0}: {1}".format(url, e.strerror))
            # TODO: handle error condition
            raise
        except IOError as e:
            self.logger.error("Could not load template from {0}: {1}".format(url, e.strerror))
            raise

    def _s3_get_template(self, url):
        raise NotImplementedError


class CloudFormation(object):
    def __init__(self, region="eu-west-1", stacks=None):
        logging.basicConfig(format='%(asctime)s %(levelname)s %(module)s: %(message)s',
                            datefmt='%d.%m.%Y %H:%M:%S',
                            level=logging.INFO)
        self.logger = logging.getLogger(__name__)

        self.conn = cloudformation.connect_to_region(region)
        if not self.conn:
            self.logger.error("Could not connect to cloudformation API in {0}. Invalid region?".format(region))
            raise AWSConnectionError("Got None connection object")

        self.logger.debug("Connected to cloudformation API at {0} with access key id: {1}".format(
            region, self.conn.aws_access_key_id))

        self.stacks = stacks
        if not self.stacks:
            self._load_stacks()

        assert isinstance(self.stacks, ResultSet)

    def _load_stacks(self):
        self.stacks = self.conn.describe_stacks()
        assert isinstance(self.stacks, ResultSet)

    def get_stacks(self):
        return self.stacks

    def get_stacks_dict(self):
        stacks_dict = {}
        for stack in self.stacks:
            stacks_dict[stack.stack_name] = {"parameters": stack.parameters, "outputs": stack.outputs}
        return stacks_dict

    def create_stack(self, stack_name, template, parameters):
        assert isinstance(template, CloudFormationTemplate)
        try:
            self.logger.info(
                "Creating stack {0} from template {1} with parameters: {2}".format(stack_name, template.url,
                                                                                   parameters))
            self.conn.create_stack(stack_name,
                                   template_body=json.dumps(template.get_template_body()),
                                   parameters=parameters)
            self.wait_to_complete(stack_name)
        except BotoServerError as e:
            self.logger.error(
                "Could not create stack {0}. Cloudformation API response: {1}".format(stack_name, e.message))

    def wait_to_complete(self, stack_name, timeout=600):
        seen_events = []
        start = time.time()

        while time.time() < (start + timeout):
            for event in self.conn.describe_stack_events(stack_name):
                if event.event_id not in seen_events:
                    seen_events.append(event.event_id)
                    if event.resource_type is "AWS::CloudFormation::Stack" and event.resource_status.endswith("CREATE_COMPLETE"):
                        self.logger.info("Stack {0} created!".format(event.logical_resource_id))
                        return True
                    elif event.resource_status.endswith("CREATE_COMPLETE"):
                        self.logger.info("Created {0}".format(event.logical_resource_id))
                    elif event.resource_status.endswith("CREATE_FAILED"):
                        self.logger.error("Could not create {0}: {1}".format(event.logical_resource_id, event.resource_status_reason))
                    elif event.resource_status.endswith("ROLLBACK_IN_PROGRESS"):
                        self.logger.warn("Rolling back {0}".format(event.logical_resource_id))
                    elif event.resource_status.endswith("ROLLBACK_COMPLETE"):
                        self.logger.error("Rollback of {0} completed".format(event.logical_resource_id))
                        return False
                    elif event.resource_status.endswith("ROLLBACK_FAILED"):
                        self.logger.error("Rollback of {0} failed".format(event.logical_resource_id))
                        return False
                    else:
                        pass
            time.sleep(10)
        return False


if __name__ == "__main__":
    cfn = CloudFormation()