from kyogre import label_image
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=FutureWarning)
    import numpy as np
    import tensorflow as tf


def determine_tier(file):
    model_file = "./image_classification_model/output_graph.pb"
    label_file = "./image_classification_model/output_labels.txt"
    input_layer = "Placeholder"
    output_layer = "final_result"
    try:
        graph = label_image.load_graph(model_file)
    except FileNotFoundError:
        return "none"
    input_name = "import/" + input_layer
    output_name = "import/" + output_layer
    input_operation = graph.get_operation_by_name(input_name)
    output_operation = graph.get_operation_by_name(output_name)
    t = label_image.read_tensor_from_image_file(
        file,
        input_height=224,
        input_width=224,
        input_mean=0,
        input_std=255)

    with tf.compat.v1.Session(graph=graph) as sess:
        tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)
        results = sess.run(output_operation.outputs[0], {
            input_operation.outputs[0]: t
        })
    results = np.squeeze(results)

    top_k = results.argsort()[-5:][::-1]
    try:
        labels = label_image.load_labels(label_file)
    except FileNotFoundError:
        return "none"
    output = ''
    for i in top_k:
        if results[i] > .01:
            output += f"{labels[i]}, {results[i]}\n"
    return output
