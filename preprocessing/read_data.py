import tensorflow as tf
import os
import urllib
import tarfile
from preprocessing.inception_preprocessing import apply_with_random_selector, distort_color


def tf_record_parser(record):
    keys_to_features = {
        "image_raw": tf.FixedLenFeature((),tf.string, default_value=""),
        "annotation_raw": tf.FixedLenFeature([],tf.string),
        "height": tf.FixedLenFeature((),tf.int64),
        "width": tf.FixedLenFeature((),tf.int64)
    }
    features = tf.parse_single_example(record, keys_to_features)

    image = tf.decode_raw(features['image_raw'],tf.uint8)
    annotation = tf.decode_raw(features['annotation_raw'],tf.uint8)

    height = tf.cast(features['height'], tf.int32)
    width = tf.cast(features['width'], tf.int32)

    image = tf.reshape(image, (height, width, 5), name="iamge_reshape")
    annotation = tf.reshape(annotation, (height, width, 1), name="annotation_reshape")

    return tf.to_float(image), tf.to_int32(annotation), (height, width)


def rescale_image_and_annotation_by_factor(image, annotation, image_shape):
    input_shape = tf.shape(image)[0:2]
    input_shape_float = tf.to_float(input_shape)

    scale = tf.random_uniform(shape=[1], minval=0.5, maxval=2)
    scaled_input_shape = tf.to_int32(tf.round(input_shape_float * scale))
    image = tf.image.resize_images(image, scaled_input_shape,
                                   method = tf.image.ResizeMethod.BILINEAR)

    annotation = tf.image.resize_images(annotation, scaled_input_shape,
                                        method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)
    return image, annotation, image_shape


def distort_randomly_image_color(image, annotation, image_shape):

    fast_mode = False
    img_float_zero_one_range = tf.to_float(image) / 255

    distorted_image = apply_with_random_selector(img_float_zero_one_range,
                                                 lambda x, ordering: distort_color(x, ordering, fast_mode=fast_mode),
                                                 num_cases=4)

    img_float_distorted_original_range = distorted_image * 255

    return img_float_distorted_original_range, annotation, image_shape


def scale_image_with_crop_padding(image, annotation, image_shape, crop_size):

    image_croped = tf.image.resize_image_with_crop_or_pad(image,crop_size,crop_size)

    # Shift all the classes by one -- to be able to differentiate
    # between zeros representing padded values and zeros representing
    # a particular semantic class.
    annotation_shifted_classes = annotation + 1

    cropped_padded_annotation = tf.image.resize_image_with_crop_or_pad(annotation_shifted_classes,crop_size,crop_size)

    mask_out_number=255
    annotation_additional_mask_out = tf.to_int32(tf.equal(cropped_padded_annotation, 0)) * (mask_out_number+1)
    cropped_padded_annotation = cropped_padded_annotation + annotation_additional_mask_out - 1

    return image_croped, tf.squeeze(cropped_padded_annotation), image_shape


def random_flip_image_and_annotation(image_tensor, annotation_tensor, image_shape):
    """Accepts image tensor and annotation tensor and returns randomly flipped tensors of both.
        The function performs random flip of image and annotation tensors with probability of 1/2
        The flip is performed or not performed for image and annotation consistently, so that
        annotation matches the image.

        Parameters
        ----------
        image_tensor : Tensor of size (width, height, 3)
            Tensor with image
        annotation_tensor : Tensor of size (width, height, 1)
            Tensor with annotation

        Returns
        -------
        randomly_flipped_img : Tensor of size (width, height, 3) of type tf.float.
            Randomly flipped image tensor
        randomly_flipped_annotation : Tensor of size (width, height, 1)
            Randomly flipped annotation tensor

        """
    original_shape = tf.shape(annotation_tensor)
    # ensure the annotation tensor has shape (width, height, 1)
    annotation_tensor = tf.cond(tf.rank(annotation_tensor) < 3,
                                lambda: tf.expand_dims(annotation_tensor, axis=2),
                                lambda: annotation_tensor)

    # Random variable: two possible outcomes (0 or 1)
    # with a 1 in 2 chance
    random_var = tf.random_uniform(maxval=2, dtype=tf.int32, shape=[])
    randomly_flipped_img = tf.cond(pred=tf.equal(random_var, 0),
                                   true_fn=lambda: tf.image.flip_left_right(image_tensor),
                                   false_fn=lambda: image_tensor)

    randomly_flipped_annotation = tf.cond(pred=tf.equal(random_var, 0),
                                          true_fn=lambda: tf.image.flip_left_right(annotation_tensor),
                                          false_fn=lambda: annotation_tensor)

    return randomly_flipped_img, tf.reshape(randomly_flipped_annotation, original_shape, name="reshape_random_flip_image_and_annotation"), image_shape


def random_flip_image_and_annotation_up_and_down(image_tensor, annotation_tensor, image_shape):
    """Accepts image tensor and annotation tensor and returns randomly flipped tensors of both.
        The function performs random flip of image and annotation tensors with probability of 1/2
        The flip is performed or not performed for image and annotation consistently, so that
        annotation matches the image.

        Parameters
        ----------
        image_tensor : Tensor of size (width, height, 3)
            Tensor with image
        annotation_tensor : Tensor of size (width, height, 1)
            Tensor with annotation

        Returns
        -------
        randomly_flipped_img : Tensor of size (width, height, 3) of type tf.float.
            Randomly flipped image tensor
        randomly_flipped_annotation : Tensor of size (width, height, 1)
            Randomly flipped annotation tensor

        """
    original_shape = tf.shape(annotation_tensor)
    # ensure the annotation tensor has shape (width, height, 1)
    annotation_tensor = tf.cond(tf.rank(annotation_tensor) < 3,
                                lambda: tf.expand_dims(annotation_tensor, axis=2),
                                lambda: annotation_tensor)

    # Random variable: two possible outcomes (0 or 1)
    # with a 1 in 2 chance
    random_var = tf.random_uniform(maxval=2, dtype=tf.int32, shape=[])
    randomly_flipped_img = tf.cond(pred=tf.equal(random_var, 0),
                                   true_fn=lambda: tf.image.flip_up_down(image_tensor),
                                   false_fn=lambda: image_tensor)

    randomly_flipped_annotation = tf.cond(pred=tf.equal(random_var, 0),
                                          true_fn=lambda: tf.image.flip_up_down(annotation_tensor),
                                          false_fn=lambda: annotation_tensor)

    return randomly_flipped_img, tf.reshape(randomly_flipped_annotation, original_shape, name="reshape_random_flip_image_and_annotation"), image_shape


def download_resnet_checkpoint_if_necessary(resnet_checkpoints_path, resnet_model_name):
    """
    Check if the resnet checkpoints are already downloaded, if not download it
    :param resnet_checkpoints_path: string: path where the properly resnet checkpoint files should be found
    :param resnet_model_name: one of resnet_v2_50 or resnet_v2_101
    :return: None
    """
    if not os.path.exists(resnet_checkpoints_path):
        # create the path and download the resnet checkpoints
        os.mkdir(resnet_checkpoints_path)

        filename = resnet_model_name + "_2017_04_14.tar.gz"

        url = "http://download.tensorflow.org/models/" + filename
        full_file_path = os.path.join(resnet_checkpoints_path, filename)
        urllib.request.urlretrieve(url, full_file_path)
        thetarfile = tarfile.open(full_file_path, "r:gz")
        thetarfile.extractall(path=resnet_checkpoints_path)
        thetarfile.close()
        print("Resnet:", resnet_model_name, "successfully downloaded.")
    else:
        print("ResNet checkpoints file successfully found.")